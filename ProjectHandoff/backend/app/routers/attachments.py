from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.deps import CurrentUser, DbDep, SettingsDep, require_roles, require_team
from app.services.subteams import has_full_access
from app.services.activity import ACTION_FILE_DELETED, ACTION_FILE_UPLOADED, log_activity
from app.services.csvstore import now_iso, new_id
from app.services.uploads import UploadValidationError, guess_mimetype, validate_upload

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


async def _get_attachment(db: DbDep, user: CurrentUser, attachment_id: str) -> dict:
    team_id = require_team(user)
    attachments = await db.query("attachments", team_id)
    attachment = next((a for a in attachments if a.get("attachment_id") == attachment_id), None)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


def _folder_for(team_id: str, project_id: str, event_id: str) -> str:
    if project_id:
        return f"Projects/{team_id}/{project_id}/files"
    if event_id:
        return f"Events/{team_id}/{event_id}/files"
    return f"TeamData/{team_id}/files"


@router.post("", status_code=201)
async def upload_attachment(
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
    task_id: str = Form(""),
    project_id: str = Form(""),
    event_id: str = Form(""),
) -> dict:
    team_id = require_team(user)
    if not (task_id or project_id or event_id):
        raise HTTPException(status_code=400, detail="An attachment must be linked to a task, project or event")

    tasks = await db.query("tasks", team_id)
    projects = await db.query("projects", team_id)
    events = await db.query("events", team_id)
    if task_id and not any(t.get("task_id") == task_id for t in tasks):
        raise HTTPException(status_code=404, detail="Task not found")
    if project_id and not any(p.get("project_id") == project_id for p in projects):
        raise HTTPException(status_code=404, detail="Project not found")
    if event_id and not any(e.get("event_id") == event_id for e in events):
        raise HTTPException(status_code=404, detail="Event not found")
    if task_id:
        task = next(t for t in tasks if t.get("task_id") == task_id)
        project_id = project_id or task.get("project_id", "")
        event_id = event_id or task.get("event_id", "")

    contents = await file.read()
    try:
        safe_name = validate_upload(file.filename or "", len(contents), settings)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    folder = _folder_for(team_id, project_id, event_id)
    await db.assert_writable(team_id)
    drive_file_id = await db.backend.upload_file(folder, safe_name, contents, guess_mimetype(safe_name))

    attachment = {
        "attachment_id": new_id(),
        "task_id": task_id,
        "project_id": project_id,
        "drive_file_id": drive_file_id,
        "file_name": safe_name,
        "uploaded_by": user["user_id"],
        "uploaded_at": now_iso(),
    }
    await db.insert("attachments", attachment, team_id)
    await log_activity(
        db, team_id=team_id, project_id=project_id, task_id=task_id,
        action=ACTION_FILE_UPLOADED, description=f"{user['name']} uploaded {safe_name}",
        user_id=user["user_id"],
    )
    return attachment


@router.get("")
async def list_attachments(user: CurrentUser, db: DbDep, task_id: str = "", project_id: str = "") -> list[dict]:
    team_id = require_team(user)
    attachments = await db.query("attachments", team_id)
    if task_id:
        attachments = [a for a in attachments if a.get("task_id") == task_id]
    if project_id:
        attachments = [a for a in attachments if a.get("project_id") == project_id]
    return sorted(attachments, key=lambda a: a.get("uploaded_at", ""), reverse=True)


@router.get("/{attachment_id}/download")
async def download_attachment(attachment_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    attachment = await _get_attachment(db, user, attachment_id)
    data = await db.backend.download_file(attachment["drive_file_id"], team_id)
    from fastapi import Response

    return Response(
        content=data,
        media_type=guess_mimetype(attachment["file_name"]),
        headers={"Content-Disposition": f'attachment; filename="{attachment["file_name"]}"'},
    )


@router.delete("/{attachment_id}")
async def delete_attachment(attachment_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    attachment = await _get_attachment(db, user, attachment_id)
    if attachment.get("uploaded_by") != user["user_id"] and not has_full_access(user):
        raise HTTPException(status_code=403, detail="Only the uploader or team admins can delete this file")

    try:
        await db.assert_writable(team_id)
        await db.backend.delete_file(attachment["drive_file_id"], team_id)
    except Exception:
        pass  # drive file already gone; still remove the row

    def fn(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r.get("attachment_id") != attachment_id]

    await db.mutate("attachments", fn, team_id)
    await log_activity(
        db, team_id=team_id, project_id=attachment.get("project_id", ""), task_id=attachment.get("task_id", ""),
        action=ACTION_FILE_DELETED, description=f"{user['name']} deleted {attachment['file_name']}",
        user_id=user["user_id"],
    )
    return {"ok": True}
