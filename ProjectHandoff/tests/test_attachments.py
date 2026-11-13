from __future__ import annotations

from conftest import auth_headers, invite_and_join


def upload(client, headers, *, task_id="", project_id="", event_id="", filename="notes.csv", content=b"a,b\n1,2\n", mime="text/csv"):
    data = {}
    if task_id:
        data["task_id"] = task_id
    if project_id:
        data["project_id"] = project_id
    if event_id:
        data["event_id"] = event_id
    return client.post(
        "/api/attachments",
        files={"file": (filename, content, mime)},
        data=data,
        headers=headers,
    )


def test_upload_download_round_trip(client, team):
    task = client.post("/api/tasks", json={"title": "Files"}, headers=team["headers"]).json()
    response = upload(client, team["headers"], task_id=task["task_id"], filename="spec v2.csv", content=b"x,y\n9,8\n")
    assert response.status_code == 201, response.text
    attachment = response.json()
    assert attachment["file_name"] == "spec_v2.csv"  # sanitized

    download = client.get(
        f"/api/attachments/{attachment['attachment_id']}/download", headers=team["headers"]
    )
    assert download.status_code == 200
    assert download.content == b"x,y\n9,8\n"
    assert "attachment" in download.headers["content-disposition"]


def test_upload_requires_reference(client, team):
    response = upload(client, team["headers"])
    assert response.status_code == 400


def test_upload_validation_rejects_bad_type(client, team):
    task = client.post("/api/tasks", json={"title": "Bad"}, headers=team["headers"]).json()
    response = upload(client, team["headers"], task_id=task["task_id"], filename="evil.exe", content=b"MZ...")
    assert response.status_code == 422
    assert "not allowed" in response.json()["detail"]


def test_upload_validation_rejects_oversize(client, team):
    task = client.post("/api/tasks", json={"title": "Big"}, headers=team["headers"]).json()
    response = upload(
        client, team["headers"], task_id=task["task_id"],
        filename="big.csv", content=b"a" * (1 * 1024 * 1024 + 10),
    )
    assert response.status_code == 422
    assert "upload limit" in response.json()["detail"]


def test_upload_unknown_task(client, team):
    response = upload(client, team["headers"], task_id="nope")
    assert response.status_code == 404


def test_upload_team_isolation(client, team):
    """Members of another team cannot upload into this team's task."""
    other = invite_and_join(client, team, "other-team@test.dev")
    # actually join a different team
    client.delete(
        f"/api/teams/{team['team_id']}/members/{other['user']['user_id']}", headers=team["headers"]
    )
    client.post("/api/teams", json={"name": "Rival"}, headers=auth_headers(other["token"]))
    task = client.post("/api/tasks", json={"title": "Mine"}, headers=team["headers"]).json()
    response = upload(client, auth_headers(other["token"]), task_id=task["task_id"])
    assert response.status_code == 404


def test_delete_attachment_permissions(client, team):
    member = invite_and_join(client, team, "uploader@test.dev")
    task = client.post("/api/tasks", json={"title": "Del"}, headers=team["headers"]).json()
    attachment = upload(
        client, auth_headers(member["token"]), task_id=task["task_id"], filename="m.csv"
    ).json()
    # uploader may delete their own file even as plain member? Only admin/coordinator per policy;
    # member deletion of own upload is allowed by uploader rule.
    response = client.delete(
        f"/api/attachments/{attachment['attachment_id']}", headers=auth_headers(member["token"])
    )
    assert response.status_code == 200


def test_project_attachment_folder(client, team):
    project = client.post("/api/projects", json={"name": "PFiles"}, headers=team["headers"]).json()
    response = upload(client, team["headers"], project_id=project["project_id"], filename="plan.md", content=b"# plan")
    assert response.status_code == 201
    listing = client.get(f"/api/attachments?project_id={project['project_id']}", headers=team["headers"]).json()
    assert len(listing) == 1
    assert listing[0]["file_name"] == "plan.md"
