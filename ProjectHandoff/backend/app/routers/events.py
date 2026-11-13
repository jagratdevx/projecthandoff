from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, require_roles, require_team
from app.schemas.api import (
    DepartmentCreateIn,
    DepartmentMemberIn,
    DepartmentUpdateIn,
    EventCreateIn,
    EventUpdateIn,
)
from app.services.activity import (
    ACTION_DEPARTMENT_CREATED,
    ACTION_DEPARTMENT_UPDATED,
    ACTION_EVENT_CREATED,
    ACTION_EVENT_UPDATED,
    ACTION_MEMBER_ADDED,
    ACTION_MEMBER_REMOVED,
    log_activity,
)
from app.services.csvstore import now_iso, new_id

router = APIRouter(prefix="/api/events", tags=["events"])
departments_router = APIRouter(prefix="/api/departments", tags=["departments"])


async def _get_event(db: DbDep, user: CurrentUser, event_id: str) -> dict:
    team_id = require_team(user)
    events = await db.query("events", team_id)
    event = next((e for e in events if e.get("event_id") == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("")
async def list_events(user: CurrentUser, db: DbDep, status: str = "") -> list[dict]:
    team_id = require_team(user)
    events = await db.query("events", team_id)
    if status:
        events = [e for e in events if e.get("status") == status]
    tasks = await db.query("tasks", team_id)
    result = []
    for event in events:
        event_tasks = [t for t in tasks if t.get("event_id") == event["event_id"]]
        completed = sum(1 for t in event_tasks if t.get("status") == "Completed")
        result.append({**event, "progress": {"total": len(event_tasks), "completed": completed}})
    return sorted(result, key=lambda e: e.get("start_date") or "9999")


@router.post("", status_code=201)
async def create_event(payload: EventCreateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    event = {
        "event_id": new_id(),
        "name": payload.name.strip(),
        "description": payload.description.strip(),
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "owner_id": user["user_id"],
        "status": payload.status,
        "created_at": now_iso(),
    }
    await db.insert("events", event, team_id)
    await log_activity(
        db, team_id=team_id, action=ACTION_EVENT_CREATED,
        description=f"{user['name']} created event “{event['name']}”", user_id=user["user_id"],
    )
    return event


@router.get("/{event_id}")
async def get_event(event_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    event = await _get_event(db, user, event_id)
    departments = [d for d in await db.query("departments", team_id) if d.get("event_id") == event_id]
    tasks = [t for t in await db.query("tasks", team_id) if t.get("event_id") == event_id]
    members_rows = await db.query("department_members", team_id)
    users = [u for u in await db.query("users") if u.get("team_id") == team_id]
    names = {u["user_id"]: u["name"] for u in users}

    dept_progress = []
    for dept in departments:
        dept_tasks = [t for t in tasks if t.get("department_id") == dept["department_id"]]
        completed = sum(1 for t in dept_tasks if t.get("status") == "Completed")
        dept_progress.append({
            **dept,
            "coordinator_name": names.get(dept.get("coordinator_id", ""), ""),
            "member_ids": [m["user_id"] for m in members_rows if m.get("department_id") == dept["department_id"]],
            "progress": {"total": len(dept_tasks), "completed": completed},
        })

    completed_total = sum(1 for t in tasks if t.get("status") == "Completed")
    return {
        "event": event,
        "departments": dept_progress,
        "tasks": tasks,
        "progress": {"total": len(tasks), "completed": completed_total},
        "members": users,
    }


@router.patch("/{event_id}")
async def update_event(event_id: str, payload: EventUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    event = await _get_event(db, user, event_id)
    if not (user["role"] in ("owner", "admin") or event.get("owner_id") == user["user_id"]):
        raise HTTPException(status_code=403, detail="Only the event owner or team admins can edit this event")

    changes: list[str] = []

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("event_id") == event_id:
                for field, value in payload.model_dump(exclude_none=True).items():
                    if row.get(field) != value:
                        changes.append(field)
                    row[field] = value
                return rows
        raise HTTPException(status_code=404, detail="Event not found")

    await db.mutate("events", fn, team_id)
    if changes:
        await log_activity(
            db, team_id=team_id, action=ACTION_EVENT_UPDATED,
            description=f"{user['name']} updated event “{event['name']}” ({', '.join(changes)})",
            user_id=user["user_id"],
        )
    events = await db.query("events", team_id)
    return next(e for e in events if e.get("event_id") == event_id)


@router.post("/{event_id}/departments", status_code=201)
async def create_department(event_id: str, payload: DepartmentCreateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    event = await _get_event(db, user, event_id)
    if payload.coordinator_id:
        users = await db.query("users")
        if not any(u.get("user_id") == payload.coordinator_id and u.get("team_id") == team_id for u in users):
            raise HTTPException(status_code=400, detail="Coordinator must be a member of your team")

    department = {
        "department_id": new_id(),
        "event_id": event_id,
        "name": payload.name.strip(),
        "coordinator_id": payload.coordinator_id,
        "description": payload.description.strip(),
        "status": "Active",
    }
    await db.insert("departments", department, team_id)
    await log_activity(
        db, team_id=team_id, action=ACTION_DEPARTMENT_CREATED,
        description=f"{user['name']} created department “{department['name']}” in event “{event['name']}”",
        user_id=user["user_id"],
    )
    return department


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

async def _get_department(db: DbDep, user: CurrentUser, department_id: str) -> dict:
    team_id = require_team(user)
    departments = await db.query("departments", team_id)
    department = next((d for d in departments if d.get("department_id") == department_id), None)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return department


@departments_router.get("/{department_id}")
async def get_department(department_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    department = await _get_department(db, user, department_id)
    tasks = [t for t in await db.query("tasks", team_id) if t.get("department_id") == department_id]
    members_rows = [m for m in await db.query("department_members", team_id) if m.get("department_id") == department_id]
    users = [u for u in await db.query("users") if u.get("team_id") == team_id]
    names = {u["user_id"]: u["name"] for u in users}
    completed = sum(1 for t in tasks if t.get("status") == "Completed")
    return {
        "department": department,
        "tasks": tasks,
        "members": [{**m, "name": names.get(m.get("user_id", ""), "")} for m in members_rows],
        "coordinator_name": names.get(department.get("coordinator_id", ""), ""),
        "progress": {"total": len(tasks), "completed": completed},
    }


@departments_router.patch("/{department_id}")
async def update_department(department_id: str, payload: DepartmentUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    department = await _get_department(db, user, department_id)
    if not (
        user["role"] in ("owner", "admin")
        or department.get("coordinator_id") == user["user_id"]
    ):
        raise HTTPException(status_code=403, detail="Only the coordinator or team admins can edit this department")
    if payload.coordinator_id:
        users = await db.query("users")
        if not any(u.get("user_id") == payload.coordinator_id and u.get("team_id") == team_id for u in users):
            raise HTTPException(status_code=400, detail="Coordinator must be a member of your team")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("department_id") == department_id:
                for field, value in payload.model_dump(exclude_none=True).items():
                    row[field] = value
                return rows
        raise HTTPException(status_code=404, detail="Department not found")

    await db.mutate("departments", fn, team_id)
    await log_activity(
        db, team_id=team_id, action=ACTION_DEPARTMENT_UPDATED,
        description=f"{user['name']} updated department “{department['name']}”", user_id=user["user_id"],
    )
    departments = await db.query("departments", team_id)
    return next(d for d in departments if d.get("department_id") == department_id)


@departments_router.post("/{department_id}/members", status_code=201)
async def add_department_member(department_id: str, payload: DepartmentMemberIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    department = await _get_department(db, user, department_id)
    if not (
        user["role"] in ("owner", "admin")
        or department.get("coordinator_id") == user["user_id"]
    ):
        raise HTTPException(status_code=403, detail="Only the coordinator or team admins can add members")
    users = await db.query("users")
    member = next((u for u in users if u.get("user_id") == payload.user_id and u.get("team_id") == team_id), None)
    if member is None:
        raise HTTPException(status_code=400, detail="User is not a member of your team")

    existing = await db.query("department_members", team_id)
    if any(m.get("department_id") == department_id and m.get("user_id") == payload.user_id for m in existing):
        raise HTTPException(status_code=409, detail="User is already a member of this department")

    row = {
        "department_id": department_id,
        "user_id": payload.user_id,
        "added_by": user["user_id"],
        "added_at": now_iso(),
    }
    await db.insert("department_members", row, team_id)
    await log_activity(
        db, team_id=team_id, action=ACTION_MEMBER_ADDED,
        description=f"{user['name']} added {member['name']} to “{department['name']}”",
        user_id=user["user_id"],
    )
    return row


@departments_router.delete("/{department_id}/members/{member_id}")
async def remove_department_member(department_id: str, member_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    department = await _get_department(db, user, department_id)
    if not (
        user["role"] in ("owner", "admin")
        or department.get("coordinator_id") == user["user_id"]
    ):
        raise HTTPException(status_code=403, detail="Only the coordinator or team admins can remove members")

    def fn(rows: list[dict]) -> list[dict]:
        return [
            r for r in rows
            if not (r.get("department_id") == department_id and r.get("user_id") == member_id)
        ]

    await db.mutate("department_members", fn, team_id)
    users = await db.query("users")
    member_name = next((u["name"] for u in users if u.get("user_id") == member_id), member_id)
    await log_activity(
        db, team_id=team_id, action=ACTION_MEMBER_REMOVED,
        description=f"{user['name']} removed {member_name} from “{department['name']}”",
        user_id=user["user_id"],
    )
    return {"ok": True}
