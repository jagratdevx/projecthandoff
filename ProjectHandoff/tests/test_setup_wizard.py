from __future__ import annotations

"""First-run setup wizard: drive-client entry via the API, first-run-only
enforcement, credential restore at startup, and oauth-start after configuration."""

import json

from fastapi.testclient import TestClient

from app.main import create_app
from conftest import make_settings


def test_setup_status_local_mode_needs_nothing(client):
    body = client.get("/api/setup/status").json()
    assert body["storage_mode"] == "local"
    assert body["needs_setup"] is False
    assert body["authorized"] is False  # meaningless locally


def _drive_settings(tmp_path, **overrides):
    return make_settings(tmp_path, storage_mode="drive", **overrides)


def test_drive_mode_unconfigured_status_allows_boot_without_host_setup(tmp_path):
    """Multi-tenant: drive mode boots with zero host-side Google setup; the
    legacy host wizard stays available but is optional."""
    app = create_app(_drive_settings(tmp_path))
    with TestClient(app) as client:
        status = client.get("/api/setup/status").json()
        assert status["needs_setup"] is False
        assert status["client_configured"] is False
        assert status["redirect_uri"].endswith("/api/drive/oauth/callback")

        # oauth start (host session) still refuses while unconfigured
        assert client.get("/api/drive/oauth/start").status_code == 503

        # a host client can be configured once, for legacy single-organizer use
        response = client.post(
            "/api/setup/drive-client",
            json={"client_id": "id.apps.googleusercontent.com", "client_secret": "GOCSPX-secret"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["client_configured"] is True

        # ...and immediately locks itself
        again = client.post(
            "/api/setup/drive-client",
            json={"client_id": "other.apps.googleusercontent.com", "client_secret": "GOCSPX-other"},
        )
        assert again.status_code == 403

        # oauth start now succeeds with the wizard-entered client id
        url = client.get("/api/drive/oauth/start?frontend_redirect=/setup").json()["authorize_url"]
        assert "id.apps.googleusercontent.com" in url

        # secrets never appear in status output
        assert "GOCSPX" not in json.dumps(client.get("/api/setup/status").json())


def test_local_mode_refuses_drive_client_configuration(client):
    response = client.post(
        "/api/setup/drive-client",
        json={"client_id": "id.apps.googleusercontent.com", "client_secret": "GOCSPX-secret"},
    )
    assert response.status_code == 400
    assert "PH_STORAGE_MODE=drive" in response.json()["detail"]


def test_wizard_credentials_survive_restart(tmp_path):
    """The client file is restored into settings on the next boot."""
    settings = _drive_settings(tmp_path, google_token_file=str(tmp_path / "tokens" / "token.json"))
    with TestClient(create_app(settings)) as first:
        saved = first.post(
            "/api/setup/drive-client",
            json={"client_id": "id.apps.googleusercontent.com", "client_secret": "GOCSPX-secret"},
        )
        assert saved.status_code == 201

    # a brand-new app instance (simulated restart), empty env creds
    settings2 = _drive_settings(tmp_path, google_token_file=str(tmp_path / "tokens" / "token.json"))
    assert settings2.drive_configured is False
    with TestClient(create_app(settings2)) as second:
        status = second.get("/api/setup/status").json()
        assert status["client_configured"] is True
        assert second.get("/api/drive/oauth/start").status_code == 200


def test_env_client_credentials_block_the_wizard(tmp_path):
    """When .env already carries the client, the wizard must not overwrite it."""
    settings = _drive_settings(
        tmp_path,
        google_client_id="from-env.apps.googleusercontent.com",
        google_client_secret="GOCSPX-env-secret",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/setup/status").json()["client_configured"] is True
        refused = client.post(
            "/api/setup/drive-client",
            json={"client_id": "x.apps.googleusercontent.com", "client_secret": "GOCSPX-x"},
        )
        assert refused.status_code == 403
