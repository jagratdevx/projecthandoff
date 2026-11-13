from __future__ import annotations

import time

from conftest import auth_headers, invite_and_join


def setup_task(client, team):
    project = client.post("/api/projects", json={"name": "HP"}, headers=team["headers"]).json()
    task = client.post(
        "/api/tasks", json={"title": "Handover Me", "project_id": project["project_id"]},
        headers=team["headers"],
    ).json()
    return project, task


def test_full_handover_accept_flow(client, team):
    new_owner = invite_and_join(client, team, "incoming@test.dev")
    project, task = setup_task(client, team)

    # assign task to the owner first
    client.patch(
        f"/api/tasks/{task['task_id']}",
        json={"assigned_to": team["owner"]["user"]["user_id"], "status": "In Progress"},
        headers=team["headers"],
    )

    response = client.post(
        "/api/handovers",
        json={
            "task_id": task["task_id"],
            "proposed_owner_id": new_owner["user"]["user_id"],
            "completed_work": "Chassis assembled, motors mounted",
            "remaining_work": "Wiring and firmware",
            "current_state": "Robot powers on, drives in circles",
            "blockers": "None",
            "next_actions": "1. Wire motors 2. Flash firmware",
            "relevant_files": "wiring-diagram.pdf",
            "deadline": "2026-04-01",
            "notes": "Parts box is under the workbench",
        },
        headers=team["headers"],
    )
    assert response.status_code == 201, response.text
    handover = response.json()
    assert handover["status"] == "pending"
    assert handover["previous_owner_id"] == team["owner"]["user"]["user_id"]

    # new owner accepts
    accept = client.post(
        f"/api/handovers/{handover['handover_id']}/accept", headers=auth_headers(new_owner["token"])
    )
    assert accept.status_code == 200, accept.text

    tasks = client.get("/api/tasks", headers=team["headers"]).json()
    updated = next(t for t in tasks if t["task_id"] == task["task_id"])
    assert updated["assigned_to"] == new_owner["user"]["user_id"]

    detail = client.get(
        f"/api/handovers/{handover['handover_id']}", headers=team["headers"]
    ).json()
    assert detail["handover"]["status"] == "accepted"
    assert detail["handover"]["accepted_at"]  # timestamp recorded

    # handover history preserved as a comment trail
    comments = client.get(f"/api/tasks/{task['task_id']}/comments", headers=team["headers"]).json()
    assert any("Accepted the handover" in c["comment"] for c in comments)


def test_handover_rejection_keeps_ownership(client, team):
    new_owner = invite_and_join(client, team, "refuser@test.dev")
    project, task = setup_task(client, team)
    client.patch(
        f"/api/tasks/{task['task_id']}",
        json={"assigned_to": team["owner"]["user"]["user_id"]},
        headers=team["headers"],
    )
    handover = client.post(
        "/api/handovers",
        json={
            "task_id": task["task_id"],
            "proposed_owner_id": new_owner["user"]["user_id"],
            "completed_work": "Half done",
        },
        headers=team["headers"],
    ).json()

    reject = client.post(
        f"/api/handovers/{handover['handover_id']}/reject",
        json={"reason": "I am already swamped with the drive base"},
        headers=auth_headers(new_owner["token"]),
    )
    assert reject.status_code == 200

    tasks = client.get("/api/tasks", headers=team["headers"]).json()
    updated = next(t for t in tasks if t["task_id"] == task["task_id"])
    assert updated["assigned_to"] == team["owner"]["user"]["user_id"]  # NOT transferred

    detail = client.get(f"/api/handovers/{handover['handover_id']}", headers=team["headers"]).json()
    assert detail["handover"]["status"] == "rejected"
    comments = client.get(f"/api/tasks/{task['task_id']}/comments", headers=team["headers"]).json()
    assert any("swamped" in c["comment"] for c in comments)  # reason recorded


def test_clarification_round_trip(client, team):
    new_owner = invite_and_join(client, team, "curious@test.dev")
    project, task = setup_task(client, team)
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"assigned_to": team["owner"]["user"]["user_id"]},
        headers=team["headers"],
    )
    handover = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": new_owner["user"]["user_id"], "completed_work": "X"},
        headers=team["headers"],
    ).json()

    clarify = client.post(
        f"/api/handovers/{handover['handover_id']}/clarify",
        json={"question": "Which motor controller is being replaced?"},
        headers=auth_headers(new_owner["token"]),
    )
    assert clarify.status_code == 200
    detail = client.get(f"/api/handovers/{handover['handover_id']}", headers=team["headers"]).json()
    assert detail["handover"]["status"] == "clarification_requested"

    # acceptance blocked while in clarification
    early = client.post(
        f"/api/handovers/{handover['handover_id']}/accept", headers=auth_headers(new_owner["token"])
    )
    assert early.status_code == 409

    respond = client.post(
        f"/api/handovers/{handover['handover_id']}/respond",
        json={"message": "The spark MAX, not the talon"},
        headers=team["headers"],
    )
    assert respond.status_code == 200
    detail = client.get(f"/api/handovers/{handover['handover_id']}", headers=team["headers"]).json()
    assert detail["handover"]["status"] == "pending"

    accept = client.post(
        f"/api/handovers/{handover['handover_id']}/accept", headers=auth_headers(new_owner["token"])
    )
    assert accept.status_code == 200


def test_only_assignee_or_admin_can_request_handover(client, team):
    outsider = invite_and_join(client, team, "outsider-h@test.dev")
    project, task = setup_task(client, team)
    response = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": team["owner"]["user"]["user_id"], "completed_work": "x"},
        headers=auth_headers(outsider["token"]),
    )
    assert response.status_code == 403


def test_proposed_owner_must_be_team_member(client, team):
    project, task = setup_task(client, team)
    response = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": "stranger", "completed_work": "x"},
        headers=team["headers"],
    )
    assert response.status_code == 400


def test_duplicate_open_handover_rejected(client, team):
    new_owner = invite_and_join(client, team, "dupe@test.dev")
    project, task = setup_task(client, team)
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"assigned_to": team["owner"]["user"]["user_id"]},
        headers=team["headers"],
    )
    first = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": new_owner["user"]["user_id"], "completed_work": "x"},
        headers=team["headers"],
    )
    assert first.status_code == 201
    second = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": new_owner["user"]["user_id"], "completed_work": "y"},
        headers=team["headers"],
    )
    assert second.status_code == 409


def test_incoming_outgoing_lists(client, team):
    new_owner = invite_and_join(client, team, "lists@test.dev")
    project, task = setup_task(client, team)
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"assigned_to": team["owner"]["user"]["user_id"]},
        headers=team["headers"],
    )
    client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": new_owner["user"]["user_id"], "completed_work": "x"},
        headers=team["headers"],
    )
    incoming = client.get(
        "/api/handovers?direction=incoming", headers=auth_headers(new_owner["token"])
    ).json()
    assert len(incoming) == 1
    assert incoming[0]["previous_owner_name"] == "Olive Owner"
    outgoing = client.get("/api/handovers?direction=outgoing", headers=team["headers"]).json()
    assert len(outgoing) == 1


def test_cancel_handover(client, team):
    new_owner = invite_and_join(client, team, "cancel@test.dev")
    project, task = setup_task(client, team)
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"assigned_to": team["owner"]["user"]["user_id"]},
        headers=team["headers"],
    )
    handover = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": new_owner["user"]["user_id"], "completed_work": "x"},
        headers=team["headers"],
    ).json()
    response = client.post(f"/api/handovers/{handover['handover_id']}/cancel", headers=team["headers"])
    assert response.status_code == 200
    detail = client.get(f"/api/handovers/{handover['handover_id']}", headers=team["headers"]).json()
    assert detail["handover"]["status"] == "cancelled"
    # ownership unchanged
    tasks = client.get("/api/tasks", headers=team["headers"]).json()
    assert next(t for t in tasks if t["task_id"] == task["task_id"])["assigned_to"] == team["owner"]["user"]["user_id"]


def test_accept_after_owner_changed_elsewhere(client, team):
    """If the task moved to someone else after the handover, acceptance still transfers correctly."""
    new_owner = invite_and_join(client, team, "late@test.dev")
    third = invite_and_join(client, team, "third@test.dev")
    project, task = setup_task(client, team)
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"assigned_to": team["owner"]["user"]["user_id"]},
        headers=team["headers"],
    )
    handover = client.post(
        "/api/handovers",
        json={"task_id": task["task_id"], "proposed_owner_id": new_owner["user"]["user_id"], "completed_work": "x"},
        headers=team["headers"],
    ).json()
    # meanwhile the task is re-assigned to a third person
    client.patch(
        f"/api/tasks/{task['task_id']}", json={"assigned_to": third["user"]["user_id"]}, headers=team["headers"]
    )
    accept = client.post(
        f"/api/handovers/{handover['handover_id']}/accept", headers=auth_headers(new_owner["token"])
    )
    assert accept.status_code == 200
    tasks = client.get("/api/tasks", headers=team["headers"]).json()
    assert next(t for t in tasks if t["task_id"] == task["task_id"])["assigned_to"] == new_owner["user"]["user_id"]
