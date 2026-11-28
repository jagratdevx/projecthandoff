from __future__ import annotations

from conftest import auth_headers, invite_and_join


def _create(client, team, name: str, description: str = ""):
    return client.post(
        f"/api/teams/{team['team_id']}/subteams",
        json={"name": name, "description": description},
        headers=team["headers"],
    )


def test_create_and_list_subteam(client, team):
    response = _create(client, team, "Design", "Posters and banners")
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["name"] == "Design"
    assert row["description"] == "Posters and banners"
    assert row["subteam_id"]
    assert f"Subteams/{team['team_id']}/Design" in row["folder_id"]

    listed = client.get(f"/api/teams/{team['team_id']}/subteams", headers=team["headers"])
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Design"]


def test_subteam_name_rules(client, team):
    assert _create(client, team, "Design").status_code == 201
    assert _create(client, team, "  design  ").status_code == 409
    assert _create(client, team, team["team"]["name"]).status_code == 409
    assert _create(client, team, "AppData").status_code == 409
    assert _create(client, team, "Bad/Name").status_code == 422


def test_delete_subteam_keeps_drive_folder(client, team):
    created = _create(client, team, "Logistics")
    subteam_id = created.json()["subteam_id"]

    deleted = client.delete(
        f"/api/teams/{team['team_id']}/subteams/{subteam_id}",
        headers=team["headers"],
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["folder_kept"] is True

    listed = client.get(f"/api/teams/{team['team_id']}/subteams", headers=team["headers"])
    assert listed.json() == []


def test_members_cannot_create_subteams(client, team):
    member = invite_and_join(client, team, "subteam-member@test.dev", role="member")
    response = client.post(
        f"/api/teams/{team['team_id']}/subteams",
        json={"name": "Design"},
        headers=auth_headers(member["token"]),
    )
    assert response.status_code == 403
