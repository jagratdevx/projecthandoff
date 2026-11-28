from __future__ import annotations

from conftest import auth_headers, invite_and_join


def _subteam(client, team, name):
    response = client.post(
        f"/api/teams/{team['team_id']}/subteams",
        json={"name": name, "description": ""},
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_member(client, team, subteam, user, role):
    response = client.post(
        f"/api/teams/{team['team_id']}/subteams/{subteam['subteam_id']}/members",
        json={"user_id": user["user"]["user_id"], "role": role},
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text


def _project(client, team, subteam, name="Scoped project"):
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "subteam_id": subteam["subteam_id"],
            "requirements": "Deliver the handover pack",
        },
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_project_requires_subteam_and_requirements_when_subteams_exist(client, team):
    subteam = _subteam(client, team, "Design")
    missing_subteam = client.post("/api/projects", json={"name": "No scope"}, headers=team["headers"])
    assert missing_subteam.status_code == 422
    missing_requirements = client.post(
        "/api/projects", json={"name": "No brief", "subteam_id": subteam["subteam_id"]}, headers=team["headers"]
    )
    assert missing_requirements.status_code == 422

    member = invite_and_join(client, team, "project-member@test.dev")
    denied = client.post(
        "/api/projects",
        json={"name": "Member project", "subteam_id": subteam["subteam_id"], "requirements": "x"},
        headers=auth_headers(member["token"]),
    )
    assert denied.status_code == 403


def test_project_visibility_and_coordinator_scope(client, team):
    design = _subteam(client, team, "Design")
    logistics = _subteam(client, team, "Logistics")
    designer = invite_and_join(client, team, "designer@test.dev")
    other = invite_and_join(client, team, "logistics-volunteer@test.dev")
    coordinator = invite_and_join(client, team, "design-coordinator@test.dev")
    _add_member(client, team, design, designer, "volunteer")
    _add_member(client, team, logistics, other, "volunteer")
    _add_member(client, team, design, coordinator, "coordinator")

    design_project = _project(client, team, design, "Design pack")
    other_project = _project(client, team, logistics, "Venue plan")

    visible = client.get("/api/projects", headers=auth_headers(designer["token"]))
    assert [p["project_id"] for p in visible.json()] == [design_project["project_id"]]

    hidden = client.get(f"/api/projects/{other_project['project_id']}", headers=auth_headers(designer["token"]))
    assert hidden.status_code == 404

    coord_headers = auth_headers(coordinator["token"])
    own_update = client.patch(
        f"/api/projects/{design_project['project_id']}", json={"description": "Updated"}, headers=coord_headers
    )
    assert own_update.status_code == 200
    cross_update = client.patch(
        f"/api/projects/{other_project['project_id']}", json={"description": "Nope"}, headers=coord_headers
    )
    assert cross_update.status_code == 404


def test_task_subteam_inheritance_and_assignee_scope(client, team):
    design = _subteam(client, team, "Design")
    logistics = _subteam(client, team, "Logistics")
    designer = invite_and_join(client, team, "task-designer@test.dev")
    other = invite_and_join(client, team, "task-other@test.dev")
    coordinator = invite_and_join(client, team, "task-coordinator@test.dev")
    _add_member(client, team, design, designer, "volunteer")
    _add_member(client, team, logistics, other, "volunteer")
    _add_member(client, team, design, coordinator, "coordinator")
    project = _project(client, team, design)

    created = client.post(
        "/api/tasks",
        json={"title": "Design task", "project_id": project["project_id"], "assigned_to": designer["user"]["user_id"]},
        headers=auth_headers(coordinator["token"]),
    )
    assert created.status_code == 201, created.text
    assert created.json()["subteam_id"] == design["subteam_id"]

    cross = client.post(
        "/api/tasks",
        json={"title": "Cross scope", "project_id": project["project_id"], "assigned_to": other["user"]["user_id"]},
        headers=auth_headers(coordinator["token"]),
    )
    assert cross.status_code == 400

    denied = client.post(
        "/api/tasks",
        json={"title": "Volunteer task", "project_id": project["project_id"]},
        headers=auth_headers(other["token"]),
    )
    assert denied.status_code == 403
