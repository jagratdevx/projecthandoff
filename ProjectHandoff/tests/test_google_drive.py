from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.services.csvstore import CsvStore
from app.services.drive.base import (
    DriveAuthError,
    DriveError,
    DriveTransientError,
    NotFoundError,
    StaleRevision,
)
from app.services.drive.factory import create_drive_backend
from app.services.drive.google_drive import GoogleDriveBackend
from app.services.drive.local import LocalDriveBackend

from fake_drive import FOLDER_MIME, FakeCreds, FakeDriveService, make_fake_http_error


@pytest.fixture()
def drive_env(tmp_path, monkeypatch):
    """A GoogleDriveBackend wired to a FakeDriveService with valid host creds."""
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"token": "t", "refresh_token": "r"}))
    service = FakeDriveService()
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **kw: service)
    backend = GoogleDriveBackend(Settings(
        google_token_file=str(token_file),
        local_data_dir=str(tmp_path / "data"),
    ))
    backend._host._creds = FakeCreds()
    backend._host._token_mtime = token_file.stat().st_mtime
    return backend, service, token_file


def run(coro):
    return asyncio.run(coro)


def test_folder_hierarchy_created_and_cached(drive_env):
    backend, service, _ = drive_env
    run(backend.ensure_root())
    folder = run(backend.ensure_folder("TeamData/team1"))
    assert folder
    cache = backend._host._folder_cache
    assert any(k.endswith("TeamData/team1") for k in cache)
    # second call served from cache
    run(backend.ensure_folder("TeamData/team1"))
    assert service.state["list_calls"] <= 5


def test_read_write_round_trip_with_revisions(drive_env):
    backend, service, _ = drive_env
    run(backend.ensure_root())
    revision = run(backend.write_file("TeamData/users.csv", "a,b\n", expected_revision=None))
    assert revision
    content, revision2 = run(backend.read_file("TeamData/users.csv"))
    assert content == "a,b\n"
    assert revision2 == revision

    new_revision = run(backend.write_file("TeamData/users.csv", "a,b,c\n", expected_revision=revision))
    assert new_revision != revision
    with pytest.raises(StaleRevision):
        run(backend.write_file("TeamData/users.csv", "x\n", expected_revision=revision))


def test_missing_file_raises_not_found(drive_env):
    backend, _, _ = drive_env
    with pytest.raises(NotFoundError):
        run(backend.read_file("TeamData/users.csv"))


def test_csv_store_on_google_backend(tmp_path, drive_env):
    backend, _, _ = drive_env
    store = CsvStore(backend)
    run(store.init())
    run(store.ensure_team("team1"))

    async def scenario():
        await store.insert(
            "users",
            {"user_id": "u1", "name": "Drive User", "email": "d@x.dev", "role": "owner",
             "team_id": "", "joined_at": "", "status": "active"},
        )

    run(scenario())
    rows, _ = run(store.read("users"))
    assert rows[0]["name"] == "Drive User"


def test_http_500_maps_to_transient(drive_env, monkeypatch):
    from googleapiclient.errors import HttpError

    backend, service, _ = drive_env

    def boom(svc):
        raise make_fake_http_error(500)

    with pytest.raises(DriveTransientError):
        run(backend._host.call(boom))


def test_http_404_maps_to_not_found(drive_env):
    backend, _, _ = drive_env

    def boom(svc):
        raise make_fake_http_error(404)

    with pytest.raises(NotFoundError):
        run(backend._host.call(boom))


def test_http_403_refreshes_then_maps_to_auth(drive_env):
    backend, service, _ = drive_env
    creds = FakeCreds()
    backend._host._creds = creds
    calls = {"n": 0}

    def boom(svc):
        calls["n"] += 1
        raise make_fake_http_error(403)

    with pytest.raises(DriveAuthError):
        run(backend._host.call(boom))
    assert calls["n"] == 2  # retried once after refresh
    assert creds.refresh_count == 1


def test_expired_token_is_refreshed_and_persisted(drive_env):
    backend, _, token_file = drive_env
    creds = FakeCreds(expired=True)
    backend._host._creds = creds

    run(backend.ensure_root())

    assert creds.refresh_count == 1
    saved = json.loads(token_file.read_text())
    assert saved["token"].startswith("tok-refreshed")


def test_refresh_failure_maps_to_auth_error(drive_env, monkeypatch):
    backend, _, _ = drive_env
    creds = FakeCreds(expired=True, refresh_fails=True)
    backend._host._creds = creds

    with pytest.raises(DriveAuthError):
        run(backend.ensure_root())


def test_upload_and_download_files(drive_env):
    backend, _, _ = drive_env
    file_id = run(backend.upload_file("Projects/t1/p1/files", "diagram.png", b"\x89PNG fake", "image/png"))
    assert file_id
    data = run(backend.download_file(file_id))
    assert data == b"\x89PNG fake"
    run(backend.delete_file(file_id))
    with pytest.raises(NotFoundError):
        run(backend.download_file(file_id))


def test_backup_round_trip_on_google_backend(drive_env):
    backend, _, _ = drive_env
    store = CsvStore(backend)
    run(store.init())

    async def scenario():
        await store.insert(
            "users",
            {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "owner", "team_id": "",
             "joined_at": "", "status": "active"},
        )
        await store.update("users", "u1", {"name": "B"})

    run(scenario())
    entries = run(backend.list_folder("Backups/global/users"))
    assert len(entries) >= 1
    restored = run(backend.download_file(entries[0]["id"]))
    assert b"A" in restored  # snapshot of the pre-update content


def test_google_status_reports_account(drive_env):
    backend, _, _ = drive_env
    status = run(backend.status())
    assert status == {"mode": "drive", "connected": True, "account": "organizer@school.edu"}


# ---------------------------------------------------------------------------
# Multi-tenant: per-team sessions and credentials
# ---------------------------------------------------------------------------

def test_team_paths_route_to_local_staging_without_any_token(tmp_path):
    """No host token, no team token: team data stages on the server disk."""
    backend = GoogleDriveBackend(Settings(
        google_token_file=str(tmp_path / "token.json"),
        local_data_dir=str(tmp_path / "data"),
    ))
    run(backend.ensure_root())
    revision = run(backend.write_file("TeamData/team9/tasks.csv", "task_id\n", expected_revision=None))
    assert revision
    # global registry also lives on the server disk in this mode
    assert (tmp_path / "data" / "TeamData" / "tasks.csv").exists() is False
    staged = tmp_path / "data" / "TeamData" / "team9" / "tasks.csv"
    assert staged.exists()


def test_team_token_is_stored_and_resolved_per_team(tmp_path, monkeypatch):
    token_file = tmp_path / "token.json"
    service = FakeDriveService()
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **kw: service)
    backend = GoogleDriveBackend(Settings(
        google_token_file=str(token_file),
        local_data_dir=str(tmp_path / "data"),
    ))
    run(backend.set_team_client("teamX", "cid", "secret", "http://localhost:8000/api/teams/drive/oauth/callback"))
    assert backend.team_client("teamX")["client_id"] == "cid"
    assert backend.team_client("other") is None
    assert backend.team_token_exists("teamX") is False

    await_save = backend.save_team_token("teamX", {"token": "t", "refresh_token": "r"})
    run(await_save)
    assert backend.team_token_exists("teamX")
    assert (tmp_path / "data" / ".tokens").exists() is False  # not in the data dir

    # team-scoped path now routes to the team's own session, not the host
    revision = run(backend.write_file("TeamData/teamX/tasks.csv", "task_id\n", expected_revision=None))
    assert revision
    assert backend._session_for_team("teamX") is not backend._host


def test_team_authorize_url_uses_team_client(tmp_path):
    backend = GoogleDriveBackend(Settings(
        google_token_file=str(tmp_path / "token.json"),
        local_data_dir=str(tmp_path / "data"),
        google_oauth_redirect_uri="http://localhost:8000/api/teams/drive/oauth/callback",
    ))
    from app.services.drive.base import DriveAuthError

    with pytest.raises(DriveAuthError):
        run(backend.team_authorize_url("teamA", "state"))
    run(backend.set_team_client("teamA", "client-a", "secret-a", ""))
    url = run(backend.team_authorize_url("teamA", "state-1"))
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-a" in url
    assert "state=state-1" in url


# ---------------------------------------------------------------------------
# Factory behaviour — never silent fallback
# ---------------------------------------------------------------------------

def test_factory_rejects_auto_without_token(tmp_path, monkeypatch,):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        storage_mode="auto",
        allow_local_storage=False,
        google_token_file=str(tmp_path / "missing.json"),
        local_data_dir=str(tmp_path / "data"),
    )
    with pytest.raises(RuntimeError) as exc:
        create_drive_backend(settings)
    assert "PH_GOOGLE_CLIENT_ID" in str(exc.value)


def test_factory_requires_explicit_optin_for_local(tmp_path):
    settings = Settings(storage_mode="local", allow_local_storage=False, local_data_dir=str(tmp_path / "data"))
    with pytest.raises(RuntimeError):
        create_drive_backend(settings)


def test_factory_selects_local_when_opted_in(tmp_path):
    settings = Settings(
        storage_mode="local", allow_local_storage=True,
        local_data_dir=str(tmp_path / "data"),
    )
    backend = create_drive_backend(settings)
    assert isinstance(backend, LocalDriveBackend)
    assert backend.mode == "local"


def test_factory_selects_drive_with_token_file(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")
    settings = Settings(
        storage_mode="auto",
        google_token_file=str(token_file),
        local_data_dir=str(tmp_path / "data"),
    )
    backend = create_drive_backend(settings)
    assert isinstance(backend, GoogleDriveBackend)
    assert backend.mode == "drive"


def test_factory_drive_mode_boots_without_host_token(tmp_path):
    """Multi-tenant: drive mode starts with zero Google setup."""
    settings = Settings(
        storage_mode="drive",
        google_token_file=str(tmp_path / "missing.json"),
        local_data_dir=str(tmp_path / "data"),
    )
    backend = create_drive_backend(settings)
    assert isinstance(backend, GoogleDriveBackend)
    assert backend.token_file_exists() is False


def test_team_status_reports_host_backed_teams_as_connected(drive_env):
    """A team without its own token runs through the host account (legacy
    deployments). team_status must report that real state instead of a
    permanent 'not connected' that nags the owner to re-authorize forever."""
    backend, _service, _token_file = drive_env
    run(backend.ensure_root())
    st = run(backend.team_status("team1"))
    assert st["connected"] is True
    assert st.get("via_host") is True
    assert st["account"]

    # Once the team connects its own Drive, the via_host marker disappears.
    team_token = backend._team_token_dir("team1") / "token.json"
    team_token.parent.mkdir(parents=True, exist_ok=True)
    team_token.write_text(json.dumps({"token": "t", "refresh_token": "r"}))
    session = backend._session_for_team("team1")
    session._creds = FakeCreds()
    session._token_mtime = team_token.stat().st_mtime
    st2 = run(backend.team_status("team1"))
    assert st2["connected"] is True
    assert "via_host" not in st2


def test_team_mapped_paths_resolve_into_anchor_folder(drive_env):
    """Regression: a mapped team path '<anchorId>/AppData/x.csv' must resolve
    INTO the anchor folder. The old resolver treated the leading anchor-ID
    segment as a folder *name*, creating a duplicate '<anchorId>/AppData'
    tree inside the team folder — reads and writes then silently hit the
    empty duplicate while the real data sat in the correct location."""
    backend, service, _ = drive_env
    run(backend.ensure_root())
    # Create a "team folder" and pin it as the team's Drive root.
    club = service.state["files"]
    club_id = run(backend._host.call(lambda svc: svc.files().create(
        body={"name": "Club", "mimeType": FOLDER_MIME}, fields="id").execute()))["id"]
    run(backend.set_team_root("team1", club_id))

    # A team-scoped write must land in <club>/AppData/tasks.csv.
    run(backend.write_file("TeamData/team1/tasks.csv", "task_id\nt1\n"))
    content, _rev = run(backend.read_file("TeamData/team1/tasks.csv"))
    assert "t1" in content

    # The team folder must contain AppData — and NEVER a folder named after
    # the anchor's own ID (the duplicate-tree bug).
    kids = run(backend._host.call(lambda svc: svc.files().list(
        q=f"'{club_id}' in parents and trashed=false",
        fields="files(name,mimeType)", pageSize=50).execute()))
    names = sorted(f["name"] for f in kids.get("files", []))
    assert "AppData" in names
    assert club_id not in names, f"self-named duplicate folder created: {names}"

    # Same for project file paths.
    run(backend.write_file("Projects/team1/p1/files/a.png", "png-bytes"))
    kids2 = run(backend._host.call(lambda svc: svc.files().list(
        q=f"'{club_id}' in parents and trashed=false",
        fields="files(name)", pageSize=50).execute()))
    names2 = sorted(f["name"] for f in kids2.get("files", []))
    assert club_id not in names2
    assert "Projects" in names2
