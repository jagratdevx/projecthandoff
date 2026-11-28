from __future__ import annotations

"""Team-owned Drive, multi-tenant edition:

- Team creation asks for the team's own OAuth client and returns a Google
  consent URL — members never touch Google anything.
- The folder is linked (and re-linked) through the team's own connected
  account, after consent; staged data migrates into the folder.
- Path mapping, sharing on join, and revocation on removal all run through
  the team's session, never the host's.
"""

import asyncio
import json

import pytest

from app.config import Settings
from app.main import create_app
from app.services.csvstore import SCHEMAS, parse_csv
from app.services.drive.google_drive import GoogleDriveBackend
from fake_drive import FOLDER_MIME, FakeCreds, FakeDriveService

from conftest import auth_headers, invite_and_join, register

FOLDER_ID = "1AbC_dEf-1234567890"
FOLDER_URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}"
CLIENT_ID = "team-client.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-team-secret"


def run(coro):
    return asyncio.run(coro)


def resources_id(app, team_id: str) -> str:
    row = next(t for t in run(app.state.db.query("teams")) if t.get("team_id") == team_id)
    return row.get("resources_folder_id", "")


# ---------------------------------------------------------------------------
# Link parsing
# ---------------------------------------------------------------------------

def test_extract_folder_id_accepts_links_and_bare_ids():
    from app.services.drive_link import drive_folder_url, extract_drive_folder_id

    assert extract_drive_folder_id(FOLDER_URL) == FOLDER_ID
    assert extract_drive_folder_id(f"{FOLDER_URL}?usp=sharing") == FOLDER_ID
    assert extract_drive_folder_id(f"https://drive.google.com/drive/u/0/folders/{FOLDER_ID}") == FOLDER_ID
    assert extract_drive_folder_id(FOLDER_ID) == FOLDER_ID
    assert extract_drive_folder_id("") == ""
    assert drive_folder_url(FOLDER_ID) == FOLDER_URL
    with pytest.raises(ValueError):
        extract_drive_folder_id("not a drive link at all")


# ---------------------------------------------------------------------------
# CSV schema migration (teams gain drive_folder_* columns)
# ---------------------------------------------------------------------------

def test_parse_csv_tolerates_old_team_header_without_drive_columns():
    old_header = ",".join(SCHEMAS["teams"][:6])  # before drive_folder_* existed
    content = f"{old_header}\nt1,Club,Desc,owner1,2026-01-01T00:00:00Z,active\n"
    rows = parse_csv("teams", content)
    assert rows[0]["team_id"] == "t1"
    assert rows[0]["drive_folder_id"] == ""


# ---------------------------------------------------------------------------
# Local development mode: links are recorded without Google verification
# ---------------------------------------------------------------------------

def test_create_team_records_drive_folder_link(client):
    owner = register(client, "owner@test.dev", "Olive Owner")
    team_id = client.post("/api/teams", json={"name": "Robotics"}, headers=auth_headers(owner["token"])).json()["team_id"]
    linked = client.patch(f"/api/teams/{team_id}", json={"drive_folder_url": FOLDER_URL}, headers=auth_headers(owner["token"]))
    assert linked.status_code == 200, linked.text
    assert linked.json()["drive_folder_id"] == FOLDER_ID
    mine = client.get("/api/teams/mine", headers=auth_headers(owner["token"])).json()
    assert mine["team"]["drive_folder_id"] == FOLDER_ID


def test_update_team_rejects_unparseable_link(client):
    owner = register(client, "owner@test.dev", "Olive Owner")
    headers = auth_headers(owner["token"])
    team_id = client.post("/api/teams", json={"name": "Robotics"}, headers=headers).json()["team_id"]
    response = client.patch(f"/api/teams/{team_id}", json={"drive_folder_url": "definitely not a link"}, headers=headers)
    assert response.status_code == 422
    assert "Drive" in response.json()["detail"]


def test_update_team_can_link_and_unlink_folder(client):
    owner = register(client, "owner@test.dev", "Olive Owner")
    headers = auth_headers(owner["token"])
    team_id = client.post("/api/teams", json={"name": "Robotics"}, headers=headers).json()["team_id"]

    linked = client.patch(f"/api/teams/{team_id}", json={"drive_folder_url": FOLDER_ID}, headers=headers)
    assert linked.status_code == 200
    assert linked.json()["drive_folder_id"] == FOLDER_ID

    unlinked = client.patch(f"/api/teams/{team_id}", json={"drive_folder_url": ""}, headers=headers)
    assert unlinked.status_code == 200
    assert unlinked.json()["drive_folder_id"] == ""


# ---------------------------------------------------------------------------
# Drive mode (multi-tenant): create → consent → link folder
# ---------------------------------------------------------------------------

def _drive_app(tmp_path, monkeypatch, folder_id: str | None = None, connect_team: str | None = None):
    """App in drive mode backed by a FakeDriveService; optionally with a
    connected team (its own OAuth client + token) and a folder in its Drive."""
    service = FakeDriveService()
    if folder_id:
        service.state["files"][folder_id] = {
            "name": "Club Drive", "parents": [], "mimeType": FOLDER_MIME,
            "content": b"", "headRevisionId": "9",
        }
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **kw: service)

    def make(**overrides) -> Settings:
        return Settings(
            storage_mode="drive", secret_key="unit-test-secret",
            google_token_file=str(tmp_path / "token.json"),
            local_data_dir=str(tmp_path / "data"),
            google_oauth_redirect_uri="http://localhost:8000/api/teams/drive/oauth/callback",
            **overrides,
        )

    backend = GoogleDriveBackend(make())
    app = create_app(make(), backend=backend)

    if connect_team:
        # Simulate a team that already connected its own Google account.
        run(backend.set_team_client(connect_team, CLIENT_ID, CLIENT_SECRET, "http://localhost:8000/api/teams/drive/oauth/callback"))
        run(backend.save_team_token(connect_team, {"token": "t", "refresh_token": "r"}))
    return app, service, backend


def _create_team(client, headers, name="Robotics"):
    return client.post(
        "/api/teams",
        json={"name": name, "drive_client_id": CLIENT_ID, "drive_client_secret": CLIENT_SECRET},
        headers=headers,
    )


def test_drive_mode_team_creation_requires_the_teams_own_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, _, _ = _drive_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        response = client.post("/api/teams", json={"name": "Robotics"}, headers=auth_headers(owner["token"]))
        assert response.status_code == 422
        assert "OAuth client" in response.json()["detail"]


def test_drive_mode_team_creation_returns_consent_url(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, backend = _drive_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        response = _create_team(client, auth_headers(owner["token"]))
        assert response.status_code == 201, response.text
        team = response.json()
        assert team["drive_folder_id"] == ""
        assert team["next_step"] == "authorize_drive"
        assert team["authorize_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert f"client_id={CLIENT_ID}" in team["authorize_url"]
        # the team's client is stored server-side, never in the response
        assert CLIENT_SECRET not in response.text
        assert backend.team_client(team["team_id"])["client_id"] == CLIENT_ID


def test_link_folder_requires_connection_first(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, _ = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]
        response = client.post(
            f"/api/teams/{team_id}/drive/folder",
            json={"drive_folder_url": FOLDER_URL}, headers=headers,
        )
        assert response.status_code == 409
        assert "Connect Google Drive first" in response.json()["detail"]


def test_connect_endpoint_stores_client_and_returns_consent_url(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, _, backend = _drive_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]
        response = client.post(
            f"/api/teams/{team_id}/drive/connect",
            json={"client_id": "second.apps.googleusercontent.com", "client_secret": "GOCSPX-2"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert "second.apps.googleusercontent.com" in response.json()["authorize_url"]
        assert backend.team_client(team_id)["client_id"] == "second.apps.googleusercontent.com"


def _ancestor_chain(state: dict, file_id: str) -> list[str]:
    chain: list[str] = []
    meta = state["files"][file_id]
    while meta.get("parents"):
        parent = meta["parents"][0]
        if parent == "root":
            break  # the fake Drive's root sentinel
        chain.append(parent)
        meta = state["files"][parent]
    return chain


def test_link_folder_verifies_through_team_account_and_maps_paths(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, _ = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]
        # team connects its own account (simulated consent completion)
        app.state.backend._session_for_team(team_id)._creds = FakeCreds()
        run(app.state.backend.save_team_token(team_id, {"token": "t", "refresh_token": "r"}))

        # a staged project exists before the folder is linked (created while
        # the team was unconnected — data lives on the server's disk)
        staged_project = client.post(
            "/api/projects", json={"name": "Before Link"}, headers=headers,
        ).json()

        response = client.post(
            f"/api/teams/{team_id}/drive/folder",
            json={"drive_folder_url": FOLDER_URL}, headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["drive_folder_id"] == FOLDER_ID

        # only the Resources folder is shared with the owner; app-data root stays private
        shared_id = resources_id(app, team_id)
        assert shared_id and shared_id != FOLDER_ID
        perms = service.state["permissions"].get(shared_id, [])
        assert any(p["emailAddress"] == "owner@test.dev" and p["role"] == "writer" for p in perms)
        assert not any(
            p["emailAddress"] == "owner@test.dev"
            for p in service.state["permissions"].get(FOLDER_ID, [])
        )

        # staged data was migrated into the team's folder (AppData/)
        projects_files = [
            f for f, m in service.state["files"].items()
            if m["name"] == "projects.csv" and m["mimeType"] != FOLDER_MIME
        ]
        assert projects_files, "projects.csv should exist in the fake Drive"
        assert any(
            FOLDER_ID in _ancestor_chain(service.state, f) for f in projects_files
        ), f"migrated projects.csv should be inside the team folder: {[_ancestor_chain(service.state, f) for f in projects_files]}"

        # migrated rows are readable through the app
        projects = client.get("/api/projects", headers=headers).json()
        assert any(p["name"] == "Before Link" for p in projects)

        # new writes land inside the team's folder
        upload = client.post(
            "/api/attachments",
            files={"file": ("notes.txt", b"hello team", "text/plain")},
            data={"project_id": staged_project["project_id"]},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
        attachment_file = next(
            f for f, m in service.state["files"].items()
            if m["name"] == "notes.txt" and m["mimeType"] == "text/plain"
        )
        chain = _ancestor_chain(service.state, attachment_file)
        assert FOLDER_ID in chain
        assert any(service.state["files"][seg]["name"] == "Projects" for seg in chain)


def test_link_folder_rejects_unknown_folder(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, _ = _drive_app(tmp_path, monkeypatch, connect_team=None)  # folder does not exist
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]
        app.state.backend._session_for_team(team_id)._creds = FakeCreds()
        run(app.state.backend.save_team_token(team_id, {"token": "t", "refresh_token": "r"}))
        response = client.post(
            f"/api/teams/{team_id}/drive/folder",
            json={"drive_folder_url": FOLDER_URL}, headers=headers,
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"]


def test_members_never_need_google_and_get_folder_access(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, _ = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]
        app.state.backend._session_for_team(team_id)._creds = FakeCreds()
        run(app.state.backend.save_team_token(team_id, {"token": "t", "refresh_token": "r"}))
        linked = client.post(
            f"/api/teams/{team_id}/drive/folder",
            json={"drive_folder_url": FOLDER_URL}, headers=headers,
        )
        assert linked.status_code == 200, linked.text

        # member joins -> granted access to Resources only
        member = invite_and_join(client, {"team_id": team_id, "headers": headers}, "mate@test.dev")
        shared_id = resources_id(app, team_id)
        perms = service.state["permissions"].get(shared_id, [])
        assert any(p["emailAddress"] == "mate@test.dev" for p in perms)
        assert not any(
            p["emailAddress"] == "mate@test.dev"
            for p in service.state["permissions"].get(FOLDER_ID, [])
        )

        # member removed -> access revoked
        members = client.get(f"/api/teams/{team_id}/members", headers=headers).json()
        member_row = next(m for m in members if m["email"] == "mate@test.dev")
        removed = client.delete(
            f"/api/teams/{team_id}/members/{member_row['user_id']}",
            headers=headers,
        )
        assert removed.status_code == 200
        perms = service.state["permissions"].get(shared_id, [])
        assert not any(p["emailAddress"] == "mate@test.dev" for p in perms)


def test_drive_share_endpoint_grants_all_members(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, _ = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]
        app.state.backend._session_for_team(team_id)._creds = FakeCreds()
        run(app.state.backend.save_team_token(team_id, {"token": "t", "refresh_token": "r"}))
        linked = client.post(
            f"/api/teams/{team_id}/drive/folder",
            json={"drive_folder_url": FOLDER_URL}, headers=headers,
        )
        assert linked.status_code == 200, linked.text
        invite_and_join(client, {"team_id": team_id, "headers": headers}, "mate1@test.dev")
        invite_and_join(client, {"team_id": team_id, "headers": headers}, "mate2@test.dev")

        # pretend the earlier grants failed: clear resource permissions, then re-share
        shared_id = resources_id(app, team_id)
        service.state["permissions"][shared_id] = []
        result = client.post(f"/api/teams/{team_id}/drive/share", headers=headers)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["shared"] == 3 and body["members"] == 3
        perms = service.state["permissions"].get(shared_id, [])
        emails = {p["emailAddress"] for p in perms}
        assert emails == {"owner@test.dev", "mate1@test.dev", "mate2@test.dev"}
        assert not service.state["permissions"].get(FOLDER_ID)


def test_team_drive_status_reports_connection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service, _ = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]

        before = client.get(f"/api/teams/{team_id}/drive/status", headers=headers).json()
        assert before["client_configured"] is True
        assert before["connected"] is False

        app.state.backend._session_for_team(team_id)._creds = FakeCreds()
        run(app.state.backend.save_team_token(team_id, {"token": "t", "refresh_token": "r"}))
        client.post(
            f"/api/teams/{team_id}/drive/folder",
            json={"drive_folder_url": FOLDER_URL}, headers=headers,
        )
        after = client.get(f"/api/teams/{team_id}/drive/status", headers=headers).json()
        assert after["connected"] is True
        assert after["folder"]["id"] == FOLDER_ID


def test_oauth_callback_exchanges_code_with_team_client(tmp_path, monkeypatch):
    """The public callback exchanges the code with the team's own client and
    redirects back to the app with a success marker."""
    from fastapi.testclient import TestClient

    app, service, backend = _drive_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = _create_team(client, headers).json()["team_id"]

        from app.security import create_signed_state
        state = create_signed_state(f"{team_id}|/team", "unit-test-secret")

        captured = {}

        class FakeResponse:
            status_code = 200
            def json(self):
                return {
                    "access_token": "tok",
                    "refresh_token": "ref",
                    "scope": "https://www.googleapis.com/auth/drive",
                }

        async def fake_post(url, data=None, headers=None, timeout=None):
            captured["data"] = data
            return FakeResponse()

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "post", staticmethod(fake_post))

        response = client.get(
            f"/api/teams/drive/oauth/callback?code=authcode&state={state}",
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        assert "/team?drive=connected" in response.headers["location"]
        assert backend.team_token_exists(team_id)
        assert captured["data"]["client_id"] == CLIENT_ID
        assert captured["data"]["client_secret"] == CLIENT_SECRET

        # a duplicate callback (browser pre-flight) is treated as success
        dup = client.get(
            f"/api/teams/drive/oauth/callback?code=authcode&state={state}",
            follow_redirects=False,
        )
        assert dup.status_code in (302, 307)
        assert "drive=connected" in dup.headers["location"]


def test_oauth_callback_rejects_forged_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, _, _ = _drive_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/api/teams/drive/oauth/callback?code=x&state=forged",
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        assert "drive=error" in response.headers["location"]
