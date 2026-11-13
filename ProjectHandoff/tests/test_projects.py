from __future__ import annotations

from conftest import auth_headers, invite_and_join


def test_create_project_defaults(client, team):
    response = client.post(
        "/api/projects",
        json={"name": "Competition Robot", "description": "Build the 2026 bot", "deadline": "2026-03-01"},
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["status"] == "Planning"
    assert project["owner_id"] == team["owner"]["user"]["user_id"]
    assert project["deadline"] == "2026-03-01"


def test_project_owner_must_be_member(client, team):
    response = client.post(
        "/api/projects",
        json={"name": "Bad", "owner_id": "not-a-member"},
        headers=team["headers"],
    )
    assert response.status_code == 400


def test_project_update_permissions(client, team):
    member = invite_and_join(client, team, "pleb@test.dev")
    project = client.post("/api/projects", json={"name": "Owned"}, headers=team["headers"]).json()

    # plain member cannot edit someone else's project
    response = client.patch(
        f"/api/projects/{project['project_id']}", json={"name": "Hacked"}, headers=auth_headers(member["token"])
    )
    assert response.status_code == 403

    # owner can
    response = client.patch(
        f"/api/projects/{project['project_id']}", json={"status": "Active", "priority": "High"},
        headers=team["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Active"
    assert response.json()["priority"] == "High"


def test_project_archive(client, team):
    project = client.post("/api/projects", json={"name": "Old Thing"}, headers=team["headers"]).json()
    response = client.post(f"/api/projects/{project['project_id']}/archive", headers=team["headers"])
    assert response.status_code == 200
    fetched = client.get("/api/projects", headers=team["headers"]).json()
    assert fetched[0]["status"] == "Archived"


def test_project_list_filters(client, team):
    client.post("/api/projects", json={"name": "Alpha", "status": "Active"}, headers=team["headers"])
    client.post("/api/projects", json={"name": "Beta Searchable"}, headers=team["headers"])
    by_status = client.get("/api/projects?status=Active", headers=team["headers"]).json()
    assert [p["name"] for p in by_status] == ["Alpha"]
    by_q = client.get("/api/projects?q=beta", headers=team["headers"]).json()
    assert [p["name"] for p in by_q] == ["Beta Searchable"]


def test_invalid_date_format_rejected(client, team):
    response = client.post(
        "/api/projects", json={"name": "Bad Date", "deadline": "March 5"}, headers=team["headers"]
    )
    assert response.status_code == 422
