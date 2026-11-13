from __future__ import annotations

from conftest import auth_headers, invite_and_join


def make_event(client, team, name="Science Fair", start="2026-05-01", end="2026-05-03"):
    return client.post(
        "/api/events",
        json={"name": name, "description": "Annual fair", "start_date": start, "end_date": end},
        headers=team["headers"],
    ).json()


def test_event_crud(client, team):
    event = make_event(client, team)
    assert event["status"] == "Planning"
    listing = client.get("/api/events", headers=team["headers"]).json()
    assert len(listing) == 1
    updated = client.patch(
        f"/api/events/{event['event_id']}", json={"status": "Active"}, headers=team["headers"]
    ).json()
    assert updated["status"] == "Active"


def test_event_update_permissions(client, team):
    member = invite_and_join(client, team, "eventmember@test.dev")
    event = make_event(client, team)
    response = client.patch(
        f"/api/events/{event['event_id']}", json={"name": "Hijacked"}, headers=auth_headers(member["token"])
    )
    assert response.status_code == 403


def test_department_workflow(client, team):
    coordinator = invite_and_join(client, team, "coord@test.dev")
    member = invite_and_join(client, team, "deptmember@test.dev")
    event = make_event(client, team)

    dept = client.post(
        f"/api/events/{event['event_id']}/departments",
        json={"name": "Logistics", "coordinator_id": coordinator["user"]["user_id"], "description": "Stuff moving"},
        headers=team["headers"],
    )
    assert dept.status_code == 201, dept.text
    dept = dept.json()

    # coordinator adds a member
    response = client.post(
        f"/api/departments/{dept['department_id']}/members",
        json={"user_id": member["user"]["user_id"]},
        headers=auth_headers(coordinator["token"]),
    )
    assert response.status_code == 201, response.text

    # duplicate add rejected
    duplicate = client.post(
        f"/api/departments/{dept['department_id']}/members",
        json={"user_id": member["user"]["user_id"]},
        headers=auth_headers(coordinator["token"]),
    )
    assert duplicate.status_code == 409

    # non-coordinator cannot add members
    sneaky = client.post(
        f"/api/departments/{dept['department_id']}/members",
        json={"user_id": team["owner"]["user"]["user_id"]},
        headers=auth_headers(member["token"]),
    )
    assert sneaky.status_code == 403

    # tasks assigned to the department
    task = client.post(
        "/api/tasks",
        json={
            "title": "Book the hall",
            "event_id": event["event_id"],
            "department_id": dept["department_id"],
            "assigned_to": member["user"]["user_id"],
        },
        headers=team["headers"],
    ).json()
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"status": "Completed"}, headers=team["headers"]
    )
    client.post(
        "/api/tasks",
        json={"title": "Order chairs", "event_id": event["event_id"], "department_id": dept["department_id"]},
        headers=team["headers"],
    )

    detail = client.get(f"/api/events/{event['event_id']}", headers=team["headers"]).json()
    assert detail["progress"] == {"total": 2, "completed": 1}
    assert len(detail["departments"]) == 1
    department = detail["departments"][0]
    assert department["progress"] == {"total": 2, "completed": 1}
    assert department["coordinator_name"] == "Coord"
    assert member["user"]["user_id"] in department["member_ids"]

    dept_detail = client.get(
        f"/api/departments/{dept['department_id']}", headers=team["headers"]
    ).json()
    assert dept_detail["progress"] == {"total": 2, "completed": 1}
    assert dept_detail["coordinator_name"] == "Coord"


def test_department_coordinator_must_be_member(client, team):
    event = make_event(client, team)
    response = client.post(
        f"/api/events/{event['event_id']}/departments",
        json={"name": "Ghost Dept", "coordinator_id": "ghost"},
        headers=team["headers"],
    )
    assert response.status_code == 400
