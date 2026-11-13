from __future__ import annotations

from conftest import auth_headers, register


def test_sync_status_lightweight(client):
    response = client.get("/api/sync/status")
    assert response.status_code == 200
    body = response.json()
    assert body["storage_mode"] == "local"
    assert "server_time" in body


def test_drive_status_reports_local_mode(client):
    response = client.get("/api/drive/status")
    assert response.status_code == 200
    body = response.json()
    assert body["storage_mode"] == "local"
    assert body["drive_configured"] is False
    assert "local development mode" in body["message"]


def test_oauth_start_requires_configuration(client):
    response = client.get("/api/drive/oauth/start")
    assert response.status_code == 503


def test_oauth_start_returns_authorize_url(client, tmp_path):
    # reconfigure the app with OAuth credentials
    from conftest import make_settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = make_settings(
        tmp_path,
        google_client_id="client-id.apps.googleusercontent.com",
        google_client_secret="secret",
        google_oauth_redirect_uri="http://localhost:8000/api/drive/oauth/callback",
    )
    with TestClient(create_app(settings)) as oauth_client:
        response = oauth_client.get("/api/drive/oauth/start")
        assert response.status_code == 200
        url = response.json()["authorize_url"]
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client-id.apps.googleusercontent.com" in url
        assert "state=" in url
        assert "access_type=offline" in url


def test_signed_state_verification_rejects_forgery(client, tmp_path):
    from conftest import make_settings
    from app.security import create_signed_state, verify_signed_state

    settings = make_settings(tmp_path)
    state = create_signed_state("nonce", settings.secret_key)
    assert verify_signed_state(state, settings.secret_key)
    assert not verify_signed_state(state + "x", settings.secret_key)
    assert not verify_signed_state("garbage", settings.secret_key)


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
