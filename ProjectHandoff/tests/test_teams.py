from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from conftest import auth_headers, invite_and_join, register


def test_create_team_and_fetch(client):
    user = register(client, "teamer@test.dev", "Teamer")
    headers = auth_headers(user["token"])
    response = client.post("/api/teams", json={"name": "Debate Society"}, headers=headers)
    assert response.status_code == 201
    mine = client.get("/api/teams/mine", headers=headers).json()
    assert mine["team"]["name"] == "Debate Society"
    assert len(mine["members"]) == 1
    assert mine["members"][0]["role"] == "owner"


def test_user_with_team_cannot_create_another(client, team):
    response = client.post("/api/teams", json={"name": "Second Team"}, headers=team["headers"])
    assert response.status_code == 409


def test_invitation_flow_joins_team_with_role(client, team):
    member = invite_and_join(client, team, "newbie@test.dev")
    assert member["user"]["team_id"] == team["team_id"]
    assert member["user"]["role"] == "member"

    members = client.get(f"/api/teams/{team['team_id']}/members", headers=team["headers"]).json()
    assert {m["email"] for m in members} == {"owner@test.dev", "newbie@test.dev"}


def test_invitation_email_must_match(client, team):
    invite = client.post(
        f"/api/teams/{team['team_id']}/invitations",
        json={"email": "planned@test.dev"},
        headers=team["headers"],
    ).json()
    response = client.post(
        "/api/auth/register",
        json={"name": "X", "email": "different@test.dev", "password": "sup3rsecret-pass", "invite_token": invite["token"]},
    )
    assert response.status_code == 400


def test_invitation_single_use(client, team):
    invite = client.post(
        f"/api/teams/{team['team_id']}/invitations",
        json={"email": "once@test.dev"},
        headers=team["headers"],
    ).json()
    first = client.post(
        "/api/auth/register",
        json={"name": "Once", "email": "once@test.dev", "password": "sup3rsecret-pass", "invite_token": invite["token"]},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/auth/register",
        json={"name": "Again", "email": "once@test.dev", "password": "sup3rsecret-pass", "invite_token": invite["token"]},
    )
    assert second.status_code == 409  # email taken; token also consumed


def test_expired_invitation_rejected(client, team):
    invite = client.post(
        f"/api/teams/{team['team_id']}/invitations",
        json={"email": "late@test.dev"},
        headers=team["headers"],
    ).json()
    # Force expiry directly in storage
    import asyncio
    from app.deps import invalidate_user_cache

    db = client.app.state.db

    async def expire():
        def fn(rows):
            for row in rows:
                if row["invitation_id"] == invite["invitation_id"]:
                    row["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            return rows

        await db.mutate("invitations", fn)

    asyncio.run(expire())
    response = client.post(
        "/api/auth/register",
        json={"name": "Late", "email": "late@test.dev", "password": "sup3rsecret-pass", "invite_token": invite["token"]},
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_role_update_and_permissions(client, team):
    member = invite_and_join(client, team, "member@test.dev")
    member_headers = auth_headers(member["token"])

    # member cannot invite
    response = client.post(
        f"/api/teams/{team['team_id']}/invitations", json={"email": "x@test.dev"}, headers=member_headers
    )
    assert response.status_code == 403

    # promote to coordinator
    response = client.patch(
        f"/api/teams/{team['team_id']}/members/{member['user']['user_id']}",
        json={"role": "coordinator"},
        headers=team["headers"],
    )
    assert response.status_code == 200

    # owner role cannot be assigned
    response = client.patch(
        f"/api/teams/{team['team_id']}/members/{member['user']['user_id']}",
        json={"role": "owner"},
        headers=team["headers"],
    )
    assert response.status_code == 400


def test_member_removal(client, team):
    member = invite_and_join(client, team, "gone@test.dev")
    response = client.delete(
        f"/api/teams/{team['team_id']}/members/{member['user']['user_id']}", headers=team["headers"]
    )
    assert response.status_code == 200
    members = client.get(f"/api/teams/{team['team_id']}/members", headers=team["headers"]).json()
    assert len(members) == 1
    me = client.get("/api/auth/me", headers=auth_headers(member["token"])).json()
    assert me["user"]["team_id"] == ""


def test_owner_cannot_be_removed(client, team):
    owner = team["owner"]
    response = client.delete(
        f"/api/teams/{team['team_id']}/members/{owner['user']['user_id']}", headers=team["headers"]
    )
    assert response.status_code == 400


def test_invitation_validation_endpoint(client, team):
    invite = client.post(
        f"/api/teams/{team['team_id']}/invitations", json={"email": "val@test.dev", "role": "coordinator"},
        headers=team["headers"],
    ).json()
    response = client.get(f"/api/invitations/validate?token={invite['token']}")
    assert response.status_code == 200
    assert response.json()["team_name"] == "Robotics Club"
    assert response.json()["role"] == "coordinator"


def test_team_isolation_between_two_teams(client, team):
    """Team data must be invisible to members of other teams."""
    other = register(client, "outsider@test.dev", "Outsider")
    other_headers = auth_headers(other["token"])
    client.post("/api/teams", json={"name": "Drama Club"}, headers=other_headers)

    project = client.post(
        "/api/projects", json={"name": "Secret Project"}, headers=team["headers"]
    ).json()
    response = client.get(f"/api/projects/{project['project_id']}", headers=other_headers)
    assert response.status_code == 404

    response = client.get("/api/projects", headers=other_headers)
    assert response.json() == []
