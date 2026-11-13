from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Ensure the module-level `app.main.app` (import side effect) never crashes
# without Google credentials during test collection.
os.environ.setdefault("PH_STORAGE_MODE", "local")
os.environ.setdefault("PH_ALLOW_LOCAL_STORAGE", "true")
os.environ.setdefault("PH_SECRET_KEY", "unit-test-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

DEFAULT_PASSWORD = "sup3rsecret-pass"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        storage_mode="local",
        allow_local_storage=True,
        secret_key="unit-test-secret",
        local_data_dir=str(tmp_path / "data"),
        max_upload_mb=1,
        frontend_url="http://localhost:5173",
        cors_origins="http://localhost:5173",
        google_client_id="",
        google_client_secret="",
        google_token_file=str(tmp_path / "token.json"),
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def app(tmp_path):
    return create_app(make_settings(tmp_path))


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str, name: str = "User", password: str = DEFAULT_PASSWORD, invite_token: str = "") -> dict:
    response = client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": password, "invite_token": invite_token},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def team(client):
    """A registered owner who has created a team."""
    owner = register(client, "owner@test.dev", "Olive Owner")
    headers = auth_headers(owner["token"])
    response = client.post(
        "/api/teams",
        json={"name": "Robotics Club", "description": "School robotics team"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    team_row = response.json()
    return {"owner": owner, "headers": headers, "team_id": team_row["team_id"], "team": team_row}


def invite_and_join(client: TestClient, team: dict, email: str, role: str = "member") -> dict:
    response = client.post(
        f"/api/teams/{team['team_id']}/invitations",
        json={"email": email, "role": role},
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]
    member = register(client, email, name=email.split("@")[0].title(), invite_token=token)
    return member
