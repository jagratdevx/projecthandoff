from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, require_roles, require_team
from app.schemas.api import CommentIn, StatusRequestIn, TaskCreateIn, TaskUpdateIn
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
from app.services.subteams import (
    can_manage_subteam,
    can_view_all,
    coordinator_of,
    get_subteam,
    has_full_access,
    members_for,
    visible_subteam_ids,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
comments_router = APIRouter(prefix="/api/tasks", tags=["comments"])


async def _get_task(db: DbDep, user: CurrentUser, task_id: str) -> dict:
    team_id = require_team(user)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _effective_subteam(db: DbDep, team_id: str, task: dict, projects: dict | None = None) -> str:
    if projects is None:
        projects = {p.get("project_id", ""): p for p in await db.query("projects", team_id)}
    project = projects.get(task.get("project_id", ""), {})
    return project.get("subteam_id", "") or task.get("subteam_id", "")


def _can_edit_task(user: dict, task: dict, coordinators: set[str], subteam_id: str = "") -> bool:
    if has_full_access(user):
        return True
    if subteam_id and subteam_id in coordinators:
        return True
    dept = task.get("department_id", "")
    return bool(dept) and dept in coordinators


async def _require_task_visible(db: DbDep, user: dict, team_id: str, task: dict) -> None:
    subteam_id = await _effective_subteam(db, team_id, task)
    if not subteam_id:
        # Legacy unscoped tasks keep their original team-wide visibility.
        return
    allowed = await visible_subteam_ids(db, user, team_id)
    if allowed is not None and subteam_id not in allowed:
        raise HTTPException(status_code=404, detail="Task not found")


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


async def _validate_assignee(db: DbDep, team_id: str, user_id: str, subteam_id: str = "") -> None:
    if subteam_id:
        members = await members_for(db, team_id, subteam_id)
        if not any(row.get("user_id") == user_id for row in members):
            raise HTTPException(status_code=400, detail="Assignee must be a member of this subteam")
        return
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
    subteam_id: str = "",
) -> list[dict]:
    team_id = require_team(user)
    projects = {p.get("project_id", ""): p for p in await db.query("projects", team_id)}
    allowed = await visible_subteam_ids(db, user, team_id)
    tasks = []
    for task in await db.query("tasks", team_id):
        effective = await _effective_subteam(db, team_id, task, projects)
        if effective:
            if allowed is not None and effective not in allowed:
                continue
        if effective and allowed is not None and effective not in allowed:
            continue
        if subteam_id and effective != subteam_id:
            continue
        tasks.append(task)
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
    project = next(
        (p for p in await db.query("projects", team_id) if p.get("project_id") == payload.project_id),
        None,
    ) if payload.project_id else None
    project_subteam = project.get("subteam_id", "") if project else ""
    effective = project_subteam or payload.subteam_id
    if effective:
        await _validate_subteam(db, team_id, effective)
        if not await can_manage_subteam(db, user, team_id, effective):
            raise HTTPException(status_code=403, detail="Only this subteam's coordinator or an overseer can create tasks for it")
    elif not has_full_access(user):
        raise HTTPException(status_code=403, detail="Only subteam coordinators and overseers can add tasks")
    if payload.subteam_id and project_subteam and payload.subteam_id != project_subteam:
        raise HTTPException(status_code=400, detail="Task subteam must match the project's subteam")

    if payload.assigned_to:
        await _validate_assignee(db, team_id, payload.assigned_to, effective)

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
        "subteam_id": effective,
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


async def _validate_subteam(db: DbDep, team_id: str, subteam_id: str) -> None:
    if subteam_id and await get_subteam(db, team_id, subteam_id) is None:
        raise HTTPException(status_code=400, detail="That subteam does not belong to your team")


def _name_of(users: list[dict], user_id: str) -> str:
    return next((u.get("name", "") for u in users if u.get("user_id") == user_id), "a member")


@router.post("/{task_id}/status-requests", status_code=201)
async def request_task_status(
    task_id: str, payload: StatusRequestIn, user: CurrentUser, db: DbDep
) -> dict:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    await _require_task_visible(db, user, team_id, task)
    if payload.status == task.get("status", ""):
        raise HTTPException(status_code=400, detail="The task is already in that status")
    existing = [r for r in await db.query("task_status_requests", team_id) if r.get("task_id") == task_id]
    if any(r.get("status") == "pending" and r.get("requested_by") == user["user_id"] for r in existing):
        raise HTTPException(status_code=409, detail="You already have a pending status request for this task")
    request = {
        "request_id": new_id(),
        "task_id": task_id,
        "team_id": team_id,
        "requested_by": user["user_id"],
        "requested_status": payload.status,
        "note": payload.note.strip(),
        "status": "pending",
        "reviewed_by": "",
        "created_at": now_iso(),
        "reviewed_at": "",
    }
    await db.insert("task_status_requests", request, team_id)
    await log_activity(
        db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task_id,
        action=ACTION_TASK_UPDATED,
        description=f"{user['name']} requested status “{payload.status}” for “{task['title']}”",
        user_id=user["user_id"],
    )
    return request


@router.get("/{task_id}/status-requests")
async def list_task_status_requests(task_id: str, user: CurrentUser, db: DbDep) -> list[dict]:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    await _require_task_visible(db, user, team_id, task)
    users = await db.query("users")
    requests = [r for r in await db.query("task_status_requests", team_id) if r.get("task_id") == task_id]
    for request in requests:
        request["requested_by_name"] = _name_of(users, request.get("requested_by", ""))
        request["reviewed_by_name"] = _name_of(users, request.get("reviewed_by", ""))
    return sorted(requests, key=lambda r: r.get("created_at", ""), reverse=True)


async def _reviewer_can_change(db: DbDep, user: dict, team_id: str, task: dict) -> bool:
    if has_full_access(user):
        return True
    subteam_id = await _effective_subteam(db, team_id, task)
    if subteam_id and subteam_id in await coordinator_of(db, team_id, user["user_id"]):
        return True
    dept = task.get("department_id", "")
    if dept:
        departments = await db.query("departments", team_id)
        return any(
            row.get("department_id") == dept and row.get("coordinator_id") == user["user_id"]
            for row in departments
        )
    return False


@router.post("/status-requests/{request_id}/approve")
async def approve_task_status(request_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    request = next(
        (r for r in await db.query("task_status_requests", team_id) if r.get("request_id") == request_id),
        None,
    )
    if request is None or request.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Pending status request not found")
    task = await _get_task(db, user, request.get("task_id", ""))
    await _require_task_visible(db, user, team_id, task)
    if not await _reviewer_can_change(db, user, team_id, task):
        raise HTTPException(status_code=403, detail="Only a coordinator or overseer can approve status changes")

    def apply(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("task_id") == task["task_id"]:
                row["status"] = request["requested_status"]
                row["version"] = str(int(row.get("version", "0") or "0") + 1)
                row["updated_at"] = now_iso()
        return rows

    def review(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("request_id") == request_id:
                row["status"] = "approved"
                row["reviewed_by"] = user["user_id"]
                row["reviewed_at"] = now_iso()
        return rows

    await db.mutate("tasks", apply, team_id)
    await db.mutate("task_status_requests", review, team_id)
    await log_activity(
        db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
        action=ACTION_TASK_STATUS,
        description=f"{user['name']} approved status “{request['requested_status']}” for “{task['title']}”",
        user_id=user["user_id"],
    )
    return {"ok": True, "status": request["requested_status"]}


@router.post("/status-requests/{request_id}/reject")
async def reject_task_status(request_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    request = next(
        (r for r in await db.query("task_status_requests", team_id) if r.get("request_id") == request_id),
        None,
    )
    if request is None or request.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Pending status request not found")
    task = await _get_task(db, user, request.get("task_id", ""))
    await _require_task_visible(db, user, team_id, task)
    if not await _reviewer_can_change(db, user, team_id, task):
        raise HTTPException(status_code=403, detail="Only a coordinator or overseer can review status changes")

    def review(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("request_id") == request_id:
                row["status"] = "rejected"
                row["reviewed_by"] = user["user_id"]
                row["reviewed_at"] = now_iso()
        return rows

    await db.mutate("task_status_requests", review, team_id)
    return {"ok": True}


@router.get("/{task_id}")
async def get_task(task_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    await _require_task_visible(db, user, team_id, task)
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
    await _require_task_visible(db, user, team_id, task)
    await _validate_refs(db, team_id, payload)
    subteam_id = await _effective_subteam(db, team_id, task)
    if payload.assigned_to:
        await _validate_assignee(db, team_id, payload.assigned_to, subteam_id)

    sub_coordinators = await coordinator_of(db, team_id, user["user_id"])
    departments = await db.query("departments", team_id)
    coordinators = sub_coordinators | {
        d["department_id"] for d in departments if d.get("coordinator_id") == user["user_id"]
    }
    if not _can_edit_task(user, task, coordinators, subteam_id):
        raise HTTPException(
            status_code=403,
            detail="Only the subteam coordinator, department coordinator or overseers can edit this task",
        )
    if payload.assigned_to and payload.assigned_to != task.get("assigned_to", ""):
        if not (has_full_access(user) or (subteam_id and subteam_id in sub_coordinators)):
            raise HTTPException(status_code=403, detail="Only a coordinator or overseer can reassign this task")

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
    await _require_task_visible(db, user, team_id, task)
    subteam_id = await _effective_subteam(db, team_id, task)
    if not (has_full_access(user) or (subteam_id and subteam_id in await coordinator_of(db, team_id, user["user_id"])) or task.get("created_by") == user["user_id"]):
        raise HTTPException(status_code=403, detail="Only the task creator, subteam coordinator or overseers can delete this task")

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
    task = await _get_task(db, user, task_id)
    await _require_task_visible(db, user, team_id, task)
    comments = [c for c in await db.query("comments", team_id) if c.get("task_id") == task_id]
    return sorted(comments, key=lambda c: c.get("created_at", ""))


@comments_router.post("/{task_id}/comments", status_code=201)
async def add_comment(task_id: str, payload: CommentIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    task = await _get_task(db, user, task_id)
    await _require_task_visible(db, user, team_id, task)
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
