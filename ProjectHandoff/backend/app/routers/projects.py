from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, require_roles, require_team
from app.schemas.api import ProjectCreateIn, ProjectUpdateIn
from app.services.activity import (
    ACTION_PROJECT_ARCHIVED,
    ACTION_PROJECT_CREATED,
    ACTION_PROJECT_UPDATED,
    log_activity,
)
from app.services.csvstore import now_iso, new_id

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _get_project(db: DbDep, user: CurrentUser, project_id: str) -> dict:
    team_id = require_team(user)
    projects = await db.query("projects", team_id)
    project = next((p for p in projects if p.get("project_id") == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _can_manage(user: dict, project: dict) -> bool:
    return user["role"] in ("owner", "admin") or project.get("owner_id") == user["user_id"]


async def _validate_owner(db: DbDep, team_id: str, owner_id: str) -> None:
    users = await db.query("users")
    member = next((u for u in users if u.get("user_id") == owner_id and u.get("team_id") == team_id), None)
    if member is None:
        raise HTTPException(status_code=400, detail="Project owner must be a member of your team")


@router.get("")
async def list_projects(user: CurrentUser, db: DbDep, status: str = "", q: str = "") -> list[dict]:
    team_id = require_team(user)
    projects = await db.query("projects", team_id)
    if status:
        projects = [p for p in projects if p.get("status") == status]
    if q:
        needle = q.lower()
        projects = [p for p in projects if needle in p.get("name", "").lower() or needle in p.get("description", "").lower()]
    return sorted(projects, key=lambda p: p.get("created_at", ""), reverse=True)


@router.post("", status_code=201)
async def create_project(payload: ProjectCreateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    owner_id = payload.owner_id or user["user_id"]
    await _validate_owner(db, team_id, owner_id)

    project = {
        "project_id": new_id(),
        "name": payload.name.strip(),
        "description": payload.description.strip(),
        "owner_id": owner_id,
        "start_date": payload.start_date,
        "deadline": payload.deadline,
        "status": payload.status,
        "priority": payload.priority,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.insert("projects", project, team_id)
    await log_activity(
        db, team_id=team_id, project_id=project["project_id"], action=ACTION_PROJECT_CREATED,
        description=f"{user['name']} created project “{project['name']}”", user_id=user["user_id"],
    )
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    project = await _get_project(db, user, project_id)
    tasks = [t for t in await db.query("tasks", team_id) if t.get("project_id") == project_id]
    completed = sum(1 for t in tasks if t.get("status") == "Completed")
    activity = [a for a in await db.query("activity") if a.get("project_id") == project_id]
    activity.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    users = {u["user_id"]: u for u in await db.query("users") if u.get("team_id") == team_id}
    return {
        "project": project,
        "tasks": tasks,
        "progress": {"total": len(tasks), "completed": completed},
        "activity": activity[:50],
        "members": list(users.values()),
    }


@router.patch("/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    project = await _get_project(db, user, project_id)
    if not _can_manage(user, project):
        raise HTTPException(status_code=403, detail="Only the project owner or team admins can edit this project")
    if payload.owner_id:
        await _validate_owner(db, team_id, payload.owner_id)

    changes: list[str] = []

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("project_id") == project_id:
                for field, value in payload.model_dump(exclude_none=True).items():
                    if row.get(field) != value:
                        changes.append(field)
                    row[field] = value
                row["updated_at"] = now_iso()
                return rows
        raise HTTPException(status_code=404, detail="Project not found")

    await db.mutate("projects", fn, team_id)
    if changes:
        await log_activity(
            db, team_id=team_id, project_id=project_id, action=ACTION_PROJECT_UPDATED,
            description=f"{user['name']} updated project fields: {', '.join(changes)}",
            user_id=user["user_id"],
        )
    projects = await db.query("projects", team_id)
    return next(p for p in projects if p.get("project_id") == project_id)


@router.post("/{project_id}/archive")
async def archive_project(project_id: str, user: CurrentUser, db: DbDep) -> dict:
    require_roles(user, "owner", "admin", "coordinator")
    team_id = require_team(user)
    project = await _get_project(db, user, project_id)
    if not _can_manage(user, project):
        raise HTTPException(status_code=403, detail="Only the project owner or team admins can archive this project")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("project_id") == project_id:
                row["status"] = "Archived"
                row["updated_at"] = now_iso()
                return rows
        raise HTTPException(status_code=404, detail="Project not found")

    await db.mutate("projects", fn, team_id)
    await log_activity(
        db, team_id=team_id, project_id=project_id, action=ACTION_PROJECT_ARCHIVED,
        description=f"{user['name']} archived project “{project['name']}”", user_id=user["user_id"],
    )
    return {"ok": True}
