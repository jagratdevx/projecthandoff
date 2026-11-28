from __future__ import annotations

from conftest import auth_headers, invite_and_join


def make_project(client, team, name="P1"):
    return client.post("/api/projects", json={"name": name}, headers=team["headers"]).json()


def test_create_and_assign_task(client, team):
    member = invite_and_join(client, team, "assignee@test.dev")
    project = make_project(client, team)
    response = client.post(
        "/api/tasks",
        json={
            "title": "Design chassis",
            "project_id": project["project_id"],
            "assigned_to": member["user"]["user_id"],
            "priority": "High",
            "deadline": "2026-02-15",
        },
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["status"] == "Not Started"
    assert task["assigned_to"] == member["user"]["user_id"]


def test_task_reference_validation(client, team):
    response = client.post("/api/tasks", json={"title": "X", "project_id": "nope"}, headers=team["headers"])
    assert response.status_code == 400
    response = client.post("/api/tasks", json={"title": "X", "assigned_to": "nope"}, headers=team["headers"])
    assert response.status_code == 400


def test_task_update_flow_and_version(client, team):
    member = invite_and_join(client, team, "worker@test.dev")
    task = client.post(
        "/api/tasks", json={"title": "Wire motors", "assigned_to": member["user"]["user_id"]},
        headers=team["headers"],
    ).json()
    headers = auth_headers(member["token"])

    direct = client.patch(
        f"/api/tasks/{task['task_id']}",
        json={"status": "In Progress"},
        headers=headers,
    )
    assert direct.status_code == 403

    requested = client.post(
        f"/api/tasks/{task['task_id']}/status-requests",
        json={"status": "In Progress"},
        headers=headers,
    )
    assert requested.status_code == 201, requested.text
    approved = client.post(
        f"/api/tasks/status-requests/{requested.json()['request_id']}/approve",
        headers=team["headers"],
    )
    assert approved.status_code == 200, approved.text

    result = client.get(f"/api/tasks/{task['task_id']}", headers=team["headers"]).json()["task"]
    assert result["version"] == "1"
    assert result["status"] == "In Progress"

    detail_edit = client.patch(
        f"/api/tasks/{task['task_id']}",
        json={"description": "Missing parts"},
        headers=headers,
    )
    assert detail_edit.status_code == 403


def test_task_edit_permission(client, team):
    member = invite_and_join(client, team, "notowner@test.dev")
    other = invite_and_join(client, team, "other@test.dev")
    task = client.post(
        "/api/tasks", json={"title": "T", "assigned_to": member["user"]["user_id"]},
        headers=team["headers"],
    ).json()
    response = client.patch(
        f"/api/tasks/{task['task_id']}", json={"status": "Completed"}, headers=auth_headers(other["token"])
    )
    assert response.status_code == 403


def test_task_filters_and_search(client, team):
    client.post("/api/tasks", json={"title": "Find me", "priority": "Critical"}, headers=team["headers"])
    client.post("/api/tasks", json={"title": "Hide me"}, headers=team["headers"])
    result = client.get("/api/tasks?q=find", headers=team["headers"]).json()
    assert [t["title"] for t in result] == ["Find me"]
    result = client.get("/api/tasks?priority=Critical", headers=team["headers"]).json()
    assert len(result) == 1


def test_task_delete_by_creator(client, team):
    task = client.post("/api/tasks", json={"title": "Doomed"}, headers=team["headers"]).json()
    response = client.delete(f"/api/tasks/{task['task_id']}", headers=team["headers"])
    assert response.status_code == 200
    assert client.get("/api/tasks", headers=team["headers"]).json() == []


def test_comments(client, team):
    member = invite_and_join(client, team, "commenter@test.dev")
    task = client.post("/api/tasks", json={"title": "C"}, headers=team["headers"]).json()
    response = client.post(
        f"/api/tasks/{task['task_id']}/comments",
        json={"comment": "First comment, with, commas"},
        headers=auth_headers(member["token"]),
    )
    assert response.status_code == 201
    comments = client.get(f"/api/tasks/{task['task_id']}/comments", headers=team["headers"]).json()
    assert len(comments) == 1
    assert comments[0]["comment"] == "First comment, with, commas"


def test_task_detail_composition(client, team):
    member = invite_and_join(client, team, "detail@test.dev")
    task = client.post(
        "/api/tasks", json={"title": "Detail", "assigned_to": member["user"]["user_id"]},
        headers=team["headers"],
    ).json()
    detail = client.get(f"/api/tasks/{task['task_id']}", headers=team["headers"]).json()
    assert detail["task"]["title"] == "Detail"
    assert "names" in detail and detail["names"][member["user"]["user_id"]] == "Detail"
    assert detail["activity"]
