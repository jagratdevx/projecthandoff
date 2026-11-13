from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import auth_headers, invite_and_join, register


def _date(offset_days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=offset_days)).isoformat()


def test_dashboard_aggregates(client, team):
    member = invite_and_join(client, team, "dash@test.dev")
    project = client.post(
        "/api/projects", json={"name": "Dash Project", "status": "Active", "deadline": _date(30)},
        headers=team["headers"],
    ).json()
    task = client.post(
        "/api/tasks",
        json={"title": "Open work", "project_id": project["project_id"], "assigned_to": member["user"]["user_id"],
              "deadline": _date(10)},
        headers=team["headers"],
    ).json()
    client.post(
        "/api/tasks",
        json={"title": "Done work", "project_id": project["project_id"], "status": "Completed"},
        headers=team["headers"],
    )
    dash = client.get("/api/dashboard", headers=auth_headers(member["token"])).json()
    assert dash["stats"]["active_projects"] == 1
    assert dash["stats"]["my_open_tasks"] == 1
    assert dash["stats"]["upcoming_deadlines"] == 1
    assert len(dash["projects"]) == 1
    assert dash["projects"][0]["progress"] == {"total": 2, "completed": 1}
    assert [t["title"] for t in dash["my_tasks"]] == ["Open work"]
    assert dash["activity"]


def test_dashboard_requires_team(client):
    user = register(client, "noteam@test.dev")
    response = client.get("/api/dashboard", headers=auth_headers(user["token"]))
    assert response.status_code == 409


def test_activity_log_records_actions(client, team):
    member = invite_and_join(client, team, "audit@test.dev")
    project = client.post("/api/projects", json={"name": "Audited"}, headers=team["headers"]).json()
    task = client.post(
        "/api/tasks", json={"title": "Logged", "project_id": project["project_id"]}, headers=team["headers"]
    ).json()
    client.patch(f"/api/tasks/{task['task_id']}", json={"status": "In Progress"}, headers=team["headers"])
    client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": member["user"]["user_id"], "completed_work": "a"},
        headers=team["headers"],
    )

    feed = client.get("/api/activity", headers=team["headers"]).json()
    actions = [a["action"] for a in feed["items"]]
    assert "project.created" in actions
    assert "task.created" in actions
    assert "task.status_changed" in actions
    assert "handover.requested" in actions
    assert feed["total"] >= 4
    # newest first
    assert feed["items"][0]["timestamp"] >= feed["items"][-1]["timestamp"]
    assert all(a["team_id"] == team["team_id"] for a in feed["items"])


def test_activity_pagination(client, team):
    for i in range(5):
        client.post("/api/tasks", json={"title": f"T{i}"}, headers=team["headers"])
    page1 = client.get("/api/activity?limit=3&offset=0", headers=team["headers"]).json()
    page2 = client.get("/api/activity?limit=3&offset=3", headers=team["headers"]).json()
    assert len(page1["items"]) == 3
    assert len(page2["items"]) >= 3
    assert page1["items"][0]["activity_id"] != page2["items"][0]["activity_id"]
