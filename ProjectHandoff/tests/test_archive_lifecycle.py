from __future__ import annotations

from conftest import auth_headers, invite_and_join, register


def _create_subteam(client, team, name="Design"):
    response = client.post(
        f"/api/teams/{team['team_id']}/subteams",
        json={"name": name, "description": ""},
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_subteam_invite_binds_email_and_role(client, team):
    subteam = _create_subteam(client, team)
    invited = client.post(
        f"/api/teams/{team['team_id']}/subteams/{subteam['subteam_id']}/invitations",
        json={"email": "scoped@test.dev", "role": "coordinator"},
        headers=team["headers"],
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["token"]

    checked = client.get(f"/api/invitations/validate?token={token}")
    assert checked.status_code == 200
    assert checked.json()["subteam_role"] == "coordinator"
    assert checked.json()["subteam_name"] == "Design"

    user = register(client, "scoped@test.dev", "Scoped Volunteer", invite_token=token)
    me = client.get("/api/auth/me", headers=auth_headers(user["token"]))
    assert me.status_code == 200
    assert any(
        row["subteam_id"] == subteam["subteam_id"] and row["role"] == "coordinator"
        for row in me.json()["subteams"]
    )


def test_complete_team_makes_memories_readonly_and_unlocks_new_team(client, team):
    subteam = _create_subteam(client, team)

    completed = client.post(
        f"/api/teams/{team['team_id']}/complete",
        json={"force": True},
        headers=team["headers"],
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["already_archived"] is False

    archived = client.get(f"/api/archive/{team['team_id']}/summary", headers=team["headers"])
    assert archived.status_code == 200
    assert archived.json()["team"]["status"] == "archived"

    memories = client.get("/api/teams/memories", headers=team["headers"])
    assert any(row["team_id"] == team["team_id"] for row in memories.json())

    sub_log = client.get(
        f"/api/archive/{team['team_id']}/subteams/{subteam['subteam_id']}/activity",
        headers=team["headers"],
    )
    assert sub_log.status_code == 200

    write = client.post(
        "/api/projects",
        json={
            "name": "Not allowed",
            "subteam_id": subteam["subteam_id"],
            "requirements": "Should still be blocked by archive",
        },
        headers=team["headers"],
    )
    assert write.status_code == 409

    new_team = client.post(
        "/api/teams",
        json={"name": "New Cycle", "description": ""},
        headers=team["headers"],
    )
    assert new_team.status_code == 201, new_team.text


def test_only_owner_or_teacher_can_complete(client, team):
    admin = invite_and_join(client, team, "archive-admin@test.dev", role="admin")
    forbidden = client.post(
        f"/api/teams/{team['team_id']}/complete",
        json={},
        headers=auth_headers(admin["token"]),
    )
    assert forbidden.status_code == 403

    promoted = client.patch(
        f"/api/teams/{team['team_id']}/members/{admin['user']['user_id']}",
        json={"role": "teacher"},
        headers=team["headers"],
    )
    assert promoted.status_code == 200, promoted.text
    allowed = client.post(
        f"/api/teams/{team['team_id']}/complete",
        json={},
        headers=auth_headers(admin["token"]),
    )
    assert allowed.status_code == 200, allowed.text


def test_reset_account_detaches_user_and_keeps_history(client, team):
    member = invite_and_join(client, team, "reset-me@test.dev", role="member")
    headers = auth_headers(member["token"])

    wrong = client.post(
        "/api/auth/account/reset",
        json={"email": "someone-else@test.dev", "confirm": True},
        headers=headers,
    )
    assert wrong.status_code == 400
    unconfirmed = client.post(
        "/api/auth/account/reset", json={"email": member["user"]["email"], "confirm": False}, headers=headers
    )
    assert unconfirmed.status_code == 422

    reset = client.post(
        "/api/auth/account/reset", json={"email": member["user"]["email"], "confirm": True}, headers=headers
    )
    assert reset.status_code == 200, reset.text
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["team"] is None
    assert me.json()["can_create_team"] is True
