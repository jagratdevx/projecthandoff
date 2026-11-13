from __future__ import annotations

import pytest

from conftest import DEFAULT_PASSWORD, auth_headers, register


def test_register_login_and_me(client):
    user = register(client, "amy@test.dev", "Amy Chen")
    assert user["user"]["email"] == "amy@test.dev"
    assert user["user"]["team_id"] == ""

    response = client.post("/api/auth/login", json={"email": "amy@test.dev", "password": DEFAULT_PASSWORD})
    assert response.status_code == 200

    me = client.get("/api/auth/me", headers=auth_headers(user["token"]))
    assert me.status_code == 200
    assert me.json()["user"]["name"] == "Amy Chen"


def test_duplicate_email_rejected(client):
    register(client, "dup@test.dev")
    response = client.post("/api/auth/register", json={"name": "Other", "email": "dup@test.dev", "password": DEFAULT_PASSWORD})
    assert response.status_code == 409


def test_wrong_password(client):
    register(client, "wrongpw@test.dev")
    response = client.post("/api/auth/login", json={"email": "wrongpw@test.dev", "password": "not-it-at-all"})
    assert response.status_code == 401


def test_short_password_rejected(client):
    response = client.post("/api/auth/register", json={"name": "S", "email": "short@x.dev", "password": "short"})
    assert response.status_code == 422


def test_tampered_token_rejected(client):
    register(client, "tamper@test.dev")
    token = client.post("/api/auth/login", json={"email": "tamper@test.dev", "password": DEFAULT_PASSWORD}).json()["token"]
    tampered = token[:-4] + ("0000" if not token.endswith("0000") else "1111")
    response = client.get("/api/auth/me", headers=auth_headers(tampered))
    assert response.status_code == 401


def test_missing_token_rejected(client):
    assert client.get("/api/auth/me").status_code == 401


def test_password_change(client):
    user = register(client, "pwchange@test.dev")
    headers = auth_headers(user["token"])
    response = client.post(
        "/api/auth/password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "brand-new-pass-99"},
        headers=headers,
    )
    assert response.status_code == 200
    old_login = client.post("/api/auth/login", json={"email": "pwchange@test.dev", "password": DEFAULT_PASSWORD})
    assert old_login.status_code == 401
    new_login = client.post("/api/auth/login", json={"email": "pwchange@test.dev", "password": "brand-new-pass-99"})
    assert new_login.status_code == 200


def test_inactive_account_cannot_authenticate(client):
    """A member deactivated by an admin loses access immediately."""
    owner = register(client, "owner-inact@test.dev", "Owner")
    owner_headers = auth_headers(owner["token"])
    team = client.post("/api/teams", json={"name": "Inactive Check"}, headers=owner_headers).json()
    invite = client.post(
        f"/api/teams/{team['team_id']}/invitations", json={"email": "inactive2@test.dev"}, headers=owner_headers
    ).json()
    member = register(client, "inactive2@test.dev", invite_token=invite["token"])
    member_token = member["token"]
    assert client.get("/api/auth/me", headers=auth_headers(member_token)).status_code == 200

    deactivate = client.patch(
        f"/api/teams/{team['team_id']}/members/{member['user']['user_id']}",
        json={"status": "inactive"},
        headers=owner_headers,
    )
    assert deactivate.status_code == 200
    assert client.get("/api/auth/me", headers=auth_headers(member_token)).status_code == 401
