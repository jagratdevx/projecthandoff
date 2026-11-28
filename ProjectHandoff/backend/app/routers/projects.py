from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, require_full_access, require_roles, require_team
from app.schemas.api import ProjectCreateIn, ProjectUpdateIn
from app.services.activity import (
    ACTION_PROJECT_ARCHIVED,
    ACTION_PROJECT_CREATED,
    ACTION_PROJECT_UPDATED,
    ACTION_SUBTEAM_PROJECT_ARCHIVED,
    ACTION_SUBTEAM_PROJECT_CREATED,
    ACTION_SUBTEAM_PROJECT_UPDATED,
    log_activity,
    log_subteam_activity,
)
from app.services.csvstore import now_iso, new_id
from app.services.subteams import (
    assignable_members,
    can_manage_subteam,
    can_view_all,
    get_subteam,
    has_full_access,
    visible_subteam_ids,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])
UNASSIGNED = "__unassigned__"


async def _get_project(db: DbDep, user: CurrentUser, project_id: str) -> dict:
    team_id = require_team(user)
    projects = await db.query("projects", team_id)
    project = next((p for p in projects if p.get("project_id") == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _visible(db: DbDep, user: dict, team_id: str, project: dict) -> bool:
    subteam_id = project.get("subteam_id", "")
    if not subteam_id:
        # Legacy unscoped projects keep their original team-wide visibility.
        return True
    allowed = await visible_subteam_ids(db, user, team_id)
    return allowed is None or subteam_id in allowed


async def _require_visible(db: DbDep, user: dict, team_id: str, project: dict) -> None:
    if not await _visible(db, user, team_id, project):
        raise HTTPException(status_code=404, detail="Project not found")


def _can_manage(user: dict, project: dict) -> bool:
    return has_full_access(user) or project.get("owner_id") == user["user_id"]


async def _can_manage_scoped(db: DbDep, user: dict, team_id: str, project: dict) -> bool:
    if has_full_access(user):
        return True
    subteam_id = project.get("subteam_id", "")
    if subteam_id and await can_manage_subteam(db, user, team_id, subteam_id):
        return True
    return not subteam_id and project.get("owner_id") == user["user_id"]


async def _validate_owner(db: DbDep, team_id: str, owner_id: str) -> None:
    users = await db.query("users")
    member = next((u for u in users if u.get("user_id") == owner_id and u.get("team_id") == team_id), None)
    if member is None:
        raise HTTPException(status_code=400, detail="Project owner must be a member of your team")


async def _validate_subteam(db: DbDep, team_id: str, subteam_id: str) -> None:
    if subteam_id and await get_subteam(db, team_id, subteam_id) is None:
        raise HTTPException(status_code=400, detail="That subteam does not belong to your team")


async def _log_project_event(
    db: DbDep,
    user: dict,
    team_id: str,
    project: dict,
    *,
    main_action: str,
    subteam_action: str,
    description: str,
) -> None:
    subteam_id = project.get("subteam_id", "")
    if subteam_id:
        subteam = await get_subteam(db, team_id, subteam_id)
        await log_subteam_activity(
            db, team_id=team_id, subteam_id=subteam_id,
            action=subteam_action, description=description,
            summary=f"“{subteam.get('name', 'Subteam') if subteam else 'Subteam'}”: {description.split(' ', 1)[-1]}",
            user_id=user["user_id"], project_id=project.get("project_id", ""),
        )
    else:
        await log_activity(
            db, team_id=team_id, project_id=project.get("project_id", ""),
            action=main_action, description=description, user_id=user["user_id"],
        )


@router.get("")
async def list_projects(
    user: CurrentUser,
    db: DbDep,
    status: str = "",
    q: str = "",
    subteam_id: str = "",
) -> list[dict]:
    team_id = require_team(user)
    requested = "" if subteam_id == UNASSIGNED else subteam_id
    if requested:
        await _validate_subteam(db, team_id, requested)
        allowed = await visible_subteam_ids(db, user, team_id)
        if allowed is not None and requested not in allowed:
            raise HTTPException(status_code=403, detail="You cannot view that subteam's projects")

    projects = await db.query("projects", team_id)
    projects = [p for p in projects if await _visible(db, user, team_id, p)]
    if requested or subteam_id == UNASSIGNED:
        projects = [p for p in projects if p.get("subteam_id", "") == requested]
    if status:
        projects = [p for p in projects if p.get("status") == status]
    if q:
        needle = q.lower()
        projects = [p for p in projects if needle in p.get("name", "").lower() or needle in p.get("description", "").lower()]
    return sorted(projects, key=lambda p: p.get("created_at", ""), reverse=True)


@router.post("", status_code=201)
async def create_project(payload: ProjectCreateIn, user: CurrentUser, db: DbDep) -> dict:
    require_full_access(user)
    team_id = require_team(user)
    await _validate_subteam(db, team_id, payload.subteam_id)
    if not payload.subteam_id and await db.query("subteams", team_id):
        raise HTTPException(status_code=422, detail="Choose a subteam for this project")
    if payload.subteam_id and not payload.requirements.strip():
        raise HTTPException(status_code=422, detail="Requirements are required for a subteam project")
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
        "subteam_id": payload.subteam_id,
        "requirements": payload.requirements.strip(),
    }
    await db.insert("projects", project, team_id)
    await _log_project_event(
        db, user, team_id, project,
        main_action=ACTION_PROJECT_CREATED,
        subteam_action=ACTION_SUBTEAM_PROJECT_CREATED,
        description=f"{user['name']} created project “{project['name']}”",
    )
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    project = await _get_project(db, user, project_id)
    await _require_visible(db, user, team_id, project)
    tasks = [t for t in await db.query("tasks", team_id) if t.get("project_id") == project_id]
    completed = sum(1 for t in tasks if t.get("status") == "Completed")
    activity = [a for a in await db.query("activity") if a.get("project_id") == project_id]
    activity.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    users = {u["user_id"]: u for u in await db.query("users") if u.get("team_id") == team_id}
    members = list(users.values())
    subteam_id = project.get("subteam_id", "")
    if subteam_id:
        members = await assignable_members(db, team_id, subteam_id)
    return {
        "project": project,
        "tasks": tasks,
        "progress": {"total": len(tasks), "completed": completed},
        "activity": activity[:50],
        "members": members,
        "assignable_members": members,
    }


@router.patch("/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    project = await _get_project(db, user, project_id)
    await _require_visible(db, user, team_id, project)
    if not await _can_manage_scoped(db, user, team_id, project):
        raise HTTPException(status_code=403, detail="Only a project owner, subteam coordinator or overseer can edit this project")
    restricted = {"subteam_id", "requirements"}
    if any(getattr(payload, field, None) is not None for field in restricted) and not has_full_access(user):
        raise HTTPException(status_code=403, detail="Only overseers can change a project's subteam or requirements")
    if payload.subteam_id:
        await _validate_subteam(db, team_id, payload.subteam_id)
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
    updated = await _get_project(db, user, project_id)
    if changes:
        await _log_project_event(
            db, user, team_id, updated,
            main_action=ACTION_PROJECT_UPDATED,
            subteam_action=ACTION_SUBTEAM_PROJECT_UPDATED,
            description=f"{user['name']} updated project fields: {', '.join(changes)}",
        )
    return updated


@router.post("/{project_id}/archive")
async def archive_project(project_id: str, user: CurrentUser, db: DbDep) -> dict:
    require_roles(user, "owner", "admin", "coordinator")
    team_id = require_team(user)
    project = await _get_project(db, user, project_id)
    await _require_visible(db, user, team_id, project)
    if not await _can_manage_scoped(db, user, team_id, project):
        raise HTTPException(status_code=403, detail="Only the project owner, subteam coordinator or overseers can archive this project")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("project_id") == project_id:
                row["status"] = "Archived"
                row["updated_at"] = now_iso()
                return rows
        raise HTTPException(status_code=404, detail="Project not found")

    await db.mutate("projects", fn, team_id)
    await _log_project_event(
        db, user, team_id, project,
        main_action=ACTION_PROJECT_ARCHIVED,
        subteam_action=ACTION_SUBTEAM_PROJECT_ARCHIVED,
        description=f"{user['name']} archived project “{project['name']}”",
    )
    return {"ok": True}
