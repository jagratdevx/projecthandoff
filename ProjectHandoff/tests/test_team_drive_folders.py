from __future__ import annotations

"""Team-scoped Drive folders: link parsing at setup, folder-verified creation,
path mapping into the team's folder, and sharing with every member."""

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


def run(coro):
    return asyncio.run(coro)


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
# Team creation with a Drive folder link (local mode records it unverified)
# ---------------------------------------------------------------------------

def test_create_team_records_drive_folder_link(client):
    owner = register(client, "owner@test.dev", "Olive Owner")
    response = client.post(
        "/api/teams",
        json={"name": "Robotics", "drive_folder_url": FOLDER_URL},
        headers=auth_headers(owner["token"]),
    )
    assert response.status_code == 201, response.text
    team = response.json()
    assert team["drive_folder_id"] == FOLDER_ID
    assert team["drive_folder_url"].startswith("https://drive.google.com/drive/folders/")
    mine = client.get("/api/teams/mine", headers=auth_headers(owner["token"])).json()
    assert mine["team"]["drive_folder_id"] == FOLDER_ID


def test_create_team_rejects_unparseable_link(client):
    owner = register(client, "owner@test.dev", "Olive Owner")
    response = client.post(
        "/api/teams",
        json={"name": "Robotics", "drive_folder_url": "definitely not a link"},
        headers=auth_headers(owner["token"]),
    )
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
# Drive mode: the link is required, verified, and paths land in the folder
# ---------------------------------------------------------------------------

def _drive_app(tmp_path, monkeypatch, folder_id: str | None = None):
    """App in drive mode backed by a FakeDriveService (optionally holding the folder)."""
    service = FakeDriveService()
    if folder_id:
        service.state["files"][folder_id] = {
            "name": "Club Drive", "parents": [], "mimeType": FOLDER_MIME,
            "content": b"", "headRevisionId": "9",
        }
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **kw: service)
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"token": "t", "refresh_token": "r"}))

    def make(**overrides) -> Settings:
        return Settings(
            storage_mode="drive", secret_key="unit-test-secret",
            google_token_file=str(token_file), local_data_dir=str(tmp_path / "data"),
            **overrides,
        )

    backend = GoogleDriveBackend(make())
    backend._creds = FakeCreds()
    backend._token_mtime = token_file.stat().st_mtime
    app = create_app(make(), backend=backend)
    return app, service


def test_drive_mode_requires_folder_link_at_team_setup(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, _ = _drive_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        response = client.post("/api/teams", json={"name": "Robotics"}, headers=auth_headers(owner["token"]))
        assert response.status_code == 422
        assert "Drive folder link" in response.json()["detail"]


def test_drive_mode_rejects_unknown_folder(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, _ = _drive_app(tmp_path, monkeypatch)  # folder does not exist in the fake
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        response = client.post(
            "/api/teams", json={"name": "Robotics", "drive_folder_url": FOLDER_URL},
            headers=auth_headers(owner["token"]),
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"]


def _ancestor_chain(state: dict, file_id: str) -> list[str]:
    chain: list[str] = []
    meta = state["files"][file_id]
    while meta.get("parents"):
        parent = meta["parents"][0]
        chain.append(parent)
        meta = state["files"][parent]
    return chain


def test_drive_mode_team_setup_verifies_shares_and_maps_paths(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        response = client.post(
            "/api/teams", json={"name": "Robotics", "drive_folder_url": FOLDER_URL},
            headers=auth_headers(owner["token"]),
        )
        assert response.status_code == 201, response.text
        team_id = response.json()["team_id"]

        # the organizer's account was granted writer access on the folder
        perms = service.state["permissions"].get(FOLDER_ID, [])
        assert any(p["emailAddress"] == "owner@test.dev" and p["role"] == "writer" for p in perms)

        # team CSV tables are created inside the pasted folder (AppData/)
        tasks = [f for f, m in service.state["files"].items() if m["name"] == "tasks.csv" and m["mimeType"] != FOLDER_MIME]
        assert tasks, "tasks.csv should exist somewhere in the fake Drive"
        assert FOLDER_ID in _ancestor_chain(service.state, tasks[0])

        # an uploaded attachment lands in the team's folder too (project upload
        # -> <team folder>/Projects/{pid}/files)
        project = client.post(
            "/api/projects", json={"name": "Season Prep"}, headers=auth_headers(owner["token"])
        ).json()
        upload = client.post(
            "/api/attachments",
            files={"file": ("notes.txt", b"hello team", "text/plain")},
            data={"project_id": project["project_id"]},
            headers=auth_headers(owner["token"]),
        )
        assert upload.status_code == 201, upload.text
        attachment_file = next(
            f for f, m in service.state["files"].items()
            if m["name"] == "notes.txt" and m["mimeType"] == "text/plain"
        )
        chain = _ancestor_chain(service.state, attachment_file)
        assert FOLDER_ID in chain
        assert any(service.state["files"][seg]["name"] == "Projects" for seg in chain)

        # member joins -> automatically granted access to the folder
        member = invite_and_join(client, {"team_id": team_id, "headers": auth_headers(owner["token"])}, "mate@test.dev")
        perms = service.state["permissions"].get(FOLDER_ID, [])
        assert any(p["emailAddress"] == "mate@test.dev" for p in perms)

        # member removed -> access revoked
        members = client.get(f"/api/teams/{team_id}/members", headers=auth_headers(owner["token"])).json()
        member_row = next(m for m in members if m["email"] == "mate@test.dev")
        removed = client.delete(
            f"/api/teams/{team_id}/members/{member_row['user_id']}",
            headers=auth_headers(owner["token"]),
        )
        assert removed.status_code == 200
        perms = service.state["permissions"].get(FOLDER_ID, [])
        assert not any(p["emailAddress"] == "mate@test.dev" for p in perms)


def test_drive_share_endpoint_grants_all_members(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    app, service = _drive_app(tmp_path, monkeypatch, folder_id=FOLDER_ID)
    with TestClient(app) as client:
        owner = register(client, "owner@test.dev", "Olive Owner")
        headers = auth_headers(owner["token"])
        team_id = client.post(
            "/api/teams", json={"name": "Robotics", "drive_folder_url": FOLDER_URL},
            headers=headers,
        ).json()["team_id"]
        invite_and_join(client, {"team_id": team_id, "headers": headers}, "mate1@test.dev")
        invite_and_join(client, {"team_id": team_id, "headers": headers}, "mate2@test.dev")

        # pretend the earlier grants failed: clear permissions, then re-share
        service.state["permissions"][FOLDER_ID] = []
        result = client.post(f"/api/teams/{team_id}/drive/share", headers=headers)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["shared"] == 3 and body["members"] == 3
        perms = service.state["permissions"].get(FOLDER_ID, [])
        emails = {p["emailAddress"] for p in perms}
        assert emails == {"owner@test.dev", "mate1@test.dev", "mate2@test.dev"}
