from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, require_roles, require_team
from app.schemas.api import CommentIn, TaskCreateIn, TaskUpdateIn
from app.services.activity import (
    ACTION_COMMENT_ADDED,
    ACTION_TASK_ASSIGNED,
    ACTION_TASK_CREATED,
    ACTION_TASK_DELETED,
    ACTION_TASK_STATUS,
    ACTION_TASK_UPDATED,
    log_activity,
)
from app.services.csvstore import now_iso, new_id

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
comments_router = APIRouter(prefix="/api/tasks", tags=["comments"])


async def _get_task(db: DbDep, user: CurrentUser, task_id: str) -> dict:
    team_id = require_team(user)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _can_edit_task(user: dict, task: dict, coordinator_of: set[str]) -> bool:
    if user["role"] in ("owner", "admin"):
        return True
    if task.get("assigned_to") == user["user_id"]:
        return True
    if task.get("created_by") == user["user_id"]:
        return True
    dept = task.get("department_id", "")
    return bool(dept) and dept in coordinator_of


async def _validate_refs(db: DbDep, team_id: str, payload: TaskCreateIn | TaskUpdateIn) -> None:
    refs = {
        "project_id": ("projects", "Project"),
        "event_id": ("events", "Event"),
        "department_id": ("departments", "Department"),
    }
    for field, (table, label) in refs.items():
        value = getattr(payload, field, "") or ""
        if not value:
            continue
        rows = await db.query(table, team_id)
        if not any(r.get(f"{table[:-1]}_id") == value for r in rows):
            raise HTTPException(status_code=400, detail=f"{label} not found in your team")


async def _validate_assignee(db: DbDep, team_id: str, user_id: str) -> None:
    users = await db.query("users")
    if not any(u.get("user_id") == user_id and u.get("team_id") == team_id and u.get("status") == "active" for u in users):
        raise HTTPException(status_code=400, detail="Assignee must be an active member of your team")


@router.get("")
async def list_tasks(
    user: CurrentUser,
    db: DbDep,
    project_id: str = "",
    event_id: str = "",
    department_id: str = "",
    assigned_to: str = "",
    status: str = "",
    priority: str = "",
    q: str = "",
) -> list[dict]:
    team_id = require_team(user)
    tasks = await db.query("tasks", team_id)
    if project_id:
        tasks = [t for t in tasks if t.get("project_id") == project_id]
    if event_id:
        tasks = [t for t in tasks if t.get("event_id") == event_id]
    if department_id:
        tasks = [t for t in tasks if t.get("department_id") == department_id]
    if assigned_to:
        tasks = [t for t in tasks if t.get("assigned_to") == assigned_to]
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    if priority:
        tasks = [t for t in tasks if t.get("priority") == priority]
    if q:
        needle = q.lower()
        tasks = [t for t in tasks if needle in t.get("title", "").lower() or needle in t.get("description", "").lower()]
    return sorted(tasks, key=lambda t: (t.get("deadline") or "9999", t.get("created_at", "")))


@router.post("", status_code=201)
async def create_task(payload: TaskCreateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    await _validate_refs(db, team_id, payload)
    if payload.assigned_to:
        await _validate_assignee(db, team_id, payload.assigned_to)

    task = {
        "task_id": new_id(),
        "project_id": payload.project_id,
        "event_id": payload.event_id,
        "department_id": payload.department_id,
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "assigned_to": payload.assigned_to,
        "created_by": user["user_id"],
        "priority": payload.priority,
        "status": payload.status,
        "deadline": payload.deadline,
        "version": "0",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.insert("tasks", task, team_id)
    if task["project_id"]:
        def touch(rows: list[dict]) -> list[dict]:
            for row in rows:
                if row.get("project_id") == task["project_id"]:
                    row["updated_at"] = now_iso()
            return rows
        await db.mutate("projects", touch, team_id)
    await log_activity(
        db, team_id=team_id, project_id=task["project_id"], task_id=task["task_id"],
        action=ACTION_TASK_CREATED, description=f"{user['name']} created task “{task['title']}”",
        user_id=user["user_id"],
    )
    if task["assigned_to"]:
        await log_activity(
            db, team_id=team_id, project_id=task["project_id"], task_id=task["task_id"],
            action=ACTION_TASK_ASSIGNED, description=f"Task assigned to {task['assigned_to']}",
            user_id=user["user_id"],
        )
    return task


@router.get("/{task_id}")
async def get_task(task_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    comments = [c for c in await db.query("comments", team_id) if c.get("task_id") == task_id]
    comments.sort(key=lambda c: c.get("created_at", ""))
    attachments = [a for a in await db.query("attachments", team_id) if a.get("task_id") == task_id]
    handovers = [h for h in await db.query("handovers", team_id) if h.get("task_id") == task_id]
    handovers.sort(key=lambda h: h.get("created_at", ""), reverse=True)
    activity = [a for a in await db.query("activity") if a.get("task_id") == task_id]
    activity.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    users = [u for u in await db.query("users") if u.get("team_id") == team_id]
    names = {u["user_id"]: u["name"] for u in users}
    return {
        "task": task,
        "comments": comments,
        "attachments": attachments,
        "handovers": handovers,
        "activity": activity[:50],
        "members": users,
        "names": names,
    }


@router.patch("/{task_id}")
async def update_task(task_id: str, payload: TaskUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    await _validate_refs(db, team_id, payload)
    if payload.assigned_to:
        await _validate_assignee(db, team_id, payload.assigned_to)

    departments = await db.query("departments", team_id)
    coordinator_of = {d["department_id"] for d in departments if d.get("coordinator_id") == user["user_id"]}
    if not _can_edit_task(user, task, coordinator_of):
        raise HTTPException(
            status_code=403,
            detail="Only the assignee, task creator, department coordinator or team admins can edit this task",
        )

    changes: list[str] = []
    old_assignee = task.get("assigned_to", "")
    old_status = task.get("status", "")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("task_id") == task_id:
                for field, value in payload.model_dump(exclude_none=True).items():
                    if row.get(field) != value:
                        changes.append(field)
                    row[field] = value
                row["version"] = str(int(row.get("version", "0") or "0") + 1)
                row["updated_at"] = now_iso()
                return rows
        raise HTTPException(status_code=404, detail="Task not found")

    await db.mutate("tasks", fn, team_id)
    if payload.assigned_to and payload.assigned_to != old_assignee:
        await log_activity(
            db, team_id=team_id, project_id=task["project_id"], task_id=task_id,
            action=ACTION_TASK_ASSIGNED, description=f"Task “{task['title']}” assigned to {payload.assigned_to}",
            user_id=user["user_id"],
        )
    if payload.status and payload.status != old_status:
        await log_activity(
            db, team_id=team_id, project_id=task["project_id"], task_id=task_id,
            action=ACTION_TASK_STATUS, description=f"Task “{task['title']}” moved to {payload.status}",
            user_id=user["user_id"],
        )
    other_changes = [c for c in changes if c not in ("assigned_to", "status")]
    if other_changes:
        await log_activity(
            db, team_id=team_id, project_id=task["project_id"], task_id=task_id,
            action=ACTION_TASK_UPDATED,
            description=f"{user['name']} updated task “{task['title']}” ({', '.join(other_changes)})",
            user_id=user["user_id"],
        )
    tasks = await db.query("tasks", team_id)
    return next(t for t in tasks if t.get("task_id") == task_id)


@router.delete("/{task_id}")
async def delete_task(task_id: str, user: CurrentUser, db: DbDep) -> dict:
    require_roles(user, "owner", "admin", "coordinator")
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    if not (user["role"] in ("owner", "admin") or task.get("created_by") == user["user_id"]):
        raise HTTPException(status_code=403, detail="Only the task creator or team admins can delete this task")

    def fn(rows: list[dict]) -> list[dict]:
        return [row for row in rows if row.get("task_id") != task_id]

    await db.mutate("tasks", fn, team_id)
    await log_activity(
        db, team_id=team_id, project_id=task["project_id"], task_id=task_id,
        action=ACTION_TASK_DELETED, description=f"{user['name']} deleted task “{task['title']}”",
        user_id=user["user_id"],
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@comments_router.get("/{task_id}/comments")
async def list_comments(task_id: str, user: CurrentUser, db: DbDep) -> list[dict]:
    team_id = require_team(user)
    await _get_task(db, user, task_id)
    comments = [c for c in await db.query("comments", team_id) if c.get("task_id") == task_id]
    return sorted(comments, key=lambda c: c.get("created_at", ""))


@comments_router.post("/{task_id}/comments", status_code=201)
async def add_comment(task_id: str, payload: CommentIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    comment = {
        "comment_id": new_id(),
        "task_id": task_id,
        "user_id": user["user_id"],
        "comment": payload.comment.strip(),
        "created_at": now_iso(),
    }
    await db.insert("comments", comment, team_id)
    await log_activity(
        db, team_id=team_id, project_id=task["project_id"], task_id=task_id,
        action=ACTION_COMMENT_ADDED, description=f"{user['name']} commented on “{task['title']}”",
        user_id=user["user_id"],
    )
    return comment
