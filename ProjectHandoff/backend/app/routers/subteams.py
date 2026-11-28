from __future__ import annotations

import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, ensure_team_access, require_full_access
from app.schemas.api import (
    SubteamCreateIn,
    SubteamInviteIn,
    SubteamMemberIn,
    SubteamMemberRoleIn,
    SubteamUpdateIn,
)
from app.security import hash_token
from app.services.activity import (
    ACTION_INVITE_CREATED,
    ACTION_SUBTEAM_CREATED,
    ACTION_SUBTEAM_DELETED,
    ACTION_SUBTEAM_INVITE_CREATED,
    ACTION_SUBTEAM_MEMBER_ADDED,
    ACTION_SUBTEAM_MEMBER_REMOVED,
    ACTION_SUBTEAM_ROLE_CHANGED,
    log_activity,
    log_subteam_activity,
)
from app.services.csvstore import new_id, now_iso
from app.services.drive.base import DriveError
from app.services.drive_link import drive_folder_url
from app.services.subteams import (
    add_membership,
    can_manage_subteam,
    get_subteam,
    is_last_coordinator,
    members_for,
    remove_membership,
    set_membership_role,
)

router = APIRouter(prefix="/api/teams", tags=["subteams"])

INVITE_TTL_DAYS = 7

# Names the app uses inside every team folder. A subteam folder must not shadow one.
RESERVED_FOLDER_NAMES = frozenset(
    {"AppData", "Backups", "Projects", "Events", "Files", "Index", "TeamData", "Subteams"}
)


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Subteam name cannot be empty")
    if len(name) > 80:
        raise HTTPException(status_code=422, detail="Subteam name must be 80 characters or fewer")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="Subteam name cannot contain path separators")
    return name


async def _managed_subteam(db: DbDep, team_id: str, subteam_id: str, user: dict) -> dict:
    subteam = await get_subteam(db, team_id, subteam_id)
    if subteam is None:
        raise HTTPException(status_code=404, detail="Subteam not found")
    if not await can_manage_subteam(db, user, team_id, subteam_id):
        raise HTTPException(status_code=403, detail="Only a full-access member or this subteam's coordinator can manage it")
    return subteam


def _summary(subteam: dict, description: str) -> str:
    return f"“{subteam.get('name', 'Subteam')}”: {description}"


@router.get("/{team_id}/subteams")
async def list_subteams(team_id: str, user: CurrentUser, db: DbDep) -> list[dict]:
    ensure_team_access(team_id, user)
    rows = await db.query("subteams", team_id)
    memberships = await members_for(db, team_id, "")
    counts = Counter(row.get("subteam_id", "") for row in memberships)
    result = []
    for row in rows:
        sid = row.get("subteam_id", "")
        my_role = next(
            (m.get("role", "") for m in memberships if m.get("subteam_id") == sid and m.get("user_id") == user["user_id"]),
            "",
        )
        result.append({
            **row,
            "my_role": my_role,
            "member_count": counts.get(sid, 0),
            "can_manage": await can_manage_subteam(db, user, team_id, sid),
        })
    return sorted(result, key=lambda row: (row.get("name", "").casefold(), row.get("created_at", "")))


@router.post("/{team_id}/subteams", status_code=201)
async def create_subteam(team_id: str, payload: SubteamCreateIn, user: CurrentUser, db: DbDep) -> dict:
    ensure_team_access(team_id, user)
    require_full_access(user)
    name = _clean_name(payload.name)

    teams = await db.query("teams")
    team = next((row for row in teams if row.get("team_id") == team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if name.casefold() == team.get("name", "").strip().casefold():
        raise HTTPException(status_code=409, detail="A subteam cannot have the same name as the team")
    if name.casefold() in {value.casefold() for value in RESERVED_FOLDER_NAMES}:
        raise HTTPException(status_code=409, detail="That name is reserved for an app folder")

    existing = await db.query("subteams", team_id)
    if any(row.get("name", "").strip().casefold() == name.casefold() for row in existing):
        raise HTTPException(status_code=409, detail="A subteam with that name already exists")

    await db.assert_writable(team_id)
    try:
        folder_id = await db.backend.ensure_folder(f"Subteams/{team_id}/{name}")
    except DriveError as exc:
        raise HTTPException(status_code=502, detail=f"Could not create the subteam's Drive folder: {exc}") from exc

    row = {
        "subteam_id": new_id(),
        "team_id": team_id,
        "name": name,
        "description": payload.description.strip(),
        "folder_id": folder_id,
        "folder_url": drive_folder_url(folder_id) if db.backend.mode == "drive" and folder_id and "/" not in folder_id else "",
        "created_at": now_iso(),
    }
    await db.insert("subteams", row, team_id)
    await log_activity(
        db,
        team_id=team_id,
        action=ACTION_SUBTEAM_CREATED,
        description=f"{user['name']} created subteam “{name}”",
        user_id=user["user_id"],
    )
    return row


@router.patch("/{team_id}/subteams/{subteam_id}")
async def update_subteam(team_id: str, subteam_id: str, payload: SubteamUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    ensure_team_access(team_id, user)
    subteam = await _managed_subteam(db, team_id, subteam_id, user)
    if payload.description is not None:
        def update(rows: list[dict]) -> list[dict]:
            for row in rows:
                if row.get("subteam_id") == subteam_id:
                    row["description"] = payload.description.strip()
            return rows

        await db.mutate("subteams", update, team_id)
    return await get_subteam(db, team_id, subteam_id) or subteam


@router.delete("/{team_id}/subteams/{subteam_id}")
async def delete_subteam(team_id: str, subteam_id: str, user: CurrentUser, db: DbDep) -> dict:
    ensure_team_access(team_id, user)
    subteam = await get_subteam(db, team_id, subteam_id)
    if subteam is None:
        raise HTTPException(status_code=404, detail="Subteam not found")
    require_full_access(user)

    referenced = (
        any(row.get("subteam_id") == subteam_id for row in await db.query("projects", team_id))
        or any(row.get("subteam_id") == subteam_id for row in await db.query("tasks", team_id))
    )
    if referenced:
        raise HTTPException(status_code=409, detail="Move or archive this subteam's projects and tasks before deleting it")

    def remove(rows: list[dict]) -> list[dict]:
        return [row for row in rows if row.get("subteam_id") != subteam_id]

    await db.mutate("subteams", remove, team_id)
    await db.mutate("subteam_members", remove, team_id)
    await log_activity(
        db,
        team_id=team_id,
        action=ACTION_SUBTEAM_DELETED,
        description=f"{user['name']} removed subteam “{subteam.get('name', '')}”",
        user_id=user["user_id"],
    )
    return {"ok": True, "folder_kept": True}


@router.get("/{team_id}/subteams/{subteam_id}/members")
async def list_subteam_members(team_id: str, subteam_id: str, user: CurrentUser, db: DbDep) -> list[dict]:
    ensure_team_access(team_id, user)
    subteam = await get_subteam(db, team_id, subteam_id)
    if subteam is None:
        raise HTTPException(status_code=404, detail="Subteam not found")
    names = {u["user_id"]: u for u in await db.query("users") if u.get("team_id") == team_id}
    result = []
    for member in await members_for(db, team_id, subteam_id):
        person = names.get(member.get("user_id", ""), {})
        result.append({
            **member,
            "name": person.get("name", ""),
            "email": person.get("email", ""),
        })
    return sorted(result, key=lambda row: (row.get("name", "").casefold(), row.get("user_id", "")))


@router.post("/{team_id}/subteams/{subteam_id}/members", status_code=201)
async def add_subteam_member(
    team_id: str, subteam_id: str, payload: SubteamMemberIn, user: CurrentUser, db: DbDep
) -> dict:
    ensure_team_access(team_id, user)
    subteam = await _managed_subteam(db, team_id, subteam_id, user)
    people = await db.query("users")
    person = next(
        (u for u in people if u.get("user_id") == payload.user_id and u.get("team_id") == team_id and u.get("status") == "active"),
        None,
    )
    if person is None:
        raise HTTPException(status_code=400, detail="That person is not an active member of your main team")
    if not await add_membership(db, team_id, subteam_id, payload.user_id, payload.role, user["user_id"]):
        raise HTTPException(status_code=409, detail="This person is already in that subteam")
    await log_subteam_activity(
        db,
        team_id=team_id,
        subteam_id=subteam_id,
        action=ACTION_SUBTEAM_MEMBER_ADDED,
        description=f"{user['name']} added {person.get('name', payload.user_id)} as {payload.role}",
        summary=_summary(subteam, f"{person.get('name', 'a member')} added as {payload.role}"),
        user_id=user["user_id"],
    )
    return {"subteam_id": subteam_id, "user_id": payload.user_id, "role": payload.role, "name": person.get("name", "")}


@router.patch("/{team_id}/subteams/{subteam_id}/members/{member_id}")
async def change_subteam_member_role(
    team_id: str, subteam_id: str, member_id: str, payload: SubteamMemberRoleIn, user: CurrentUser, db: DbDep
) -> dict:
    ensure_team_access(team_id, user)
    subteam = await _managed_subteam(db, team_id, subteam_id, user)
    if await is_last_coordinator(db, team_id, subteam_id, member_id) and payload.role != "coordinator":
        raise HTTPException(status_code=409, detail="A subteam must keep at least one coordinator")
    if not await set_membership_role(db, team_id, subteam_id, member_id, payload.role):
        raise HTTPException(status_code=404, detail="That person is not in this subteam")
    await log_subteam_activity(
        db,
        team_id=team_id,
        subteam_id=subteam_id,
        action=ACTION_SUBTEAM_ROLE_CHANGED,
        description=f"{user['name']} changed a subteam role to {payload.role}",
        summary=_summary(subteam, f"a role changed to {payload.role}"),
        user_id=user["user_id"],
    )
    return {"subteam_id": subteam_id, "user_id": member_id, "role": payload.role}


@router.delete("/{team_id}/subteams/{subteam_id}/members/{member_id}")
async def remove_subteam_member(
    team_id: str, subteam_id: str, member_id: str, user: CurrentUser, db: DbDep
) -> dict:
    ensure_team_access(team_id, user)
    subteam = await _managed_subteam(db, team_id, subteam_id, user)
    if await is_last_coordinator(db, team_id, subteam_id, member_id):
        raise HTTPException(status_code=409, detail="A subteam must keep at least one coordinator")
    if not await remove_membership(db, team_id, subteam_id, member_id):
        raise HTTPException(status_code=404, detail="That person is not in this subteam")
    await log_subteam_activity(
        db,
        team_id=team_id,
        subteam_id=subteam_id,
        action=ACTION_SUBTEAM_MEMBER_REMOVED,
        description=f"{user['name']} removed a member from the subteam",
        summary=_summary(subteam, "a member was removed"),
        user_id=user["user_id"],
    )
    return {"ok": True}


@router.post("/{team_id}/subteams/{subteam_id}/invitations", status_code=201)
async def create_subteam_invitation(
    team_id: str, subteam_id: str, payload: SubteamInviteIn, user: CurrentUser, db: DbDep
) -> dict:
    ensure_team_access(team_id, user)
    subteam = await _managed_subteam(db, team_id, subteam_id, user)
    email = payload.email.lower().strip()
    people = await db.query("users")
    if any(u.get("email", "").lower() == email and u.get("team_id") == team_id for u in people):
        raise HTTPException(status_code=409, detail="This person is already a member of the main team")

    raw_token = secrets.token_urlsafe(24)
    invitation = {
        "invitation_id": new_id(),
        "team_id": team_id,
        "email": email,
        "role": "member",
        "subteam_id": subteam_id,
        "subteam_role": payload.role,
        "token_hash": hash_token(raw_token),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)).isoformat(),
        "status": "pending",
    }
    await db.insert("invitations", invitation)
    await log_subteam_activity(
        db,
        team_id=team_id,
        subteam_id=subteam_id,
        action=ACTION_SUBTEAM_INVITE_CREATED,
        description=f"{user['name']} invited {email} as {payload.role}",
        summary=_summary(subteam, f"{email} invited as {payload.role}"),
        user_id=user["user_id"],
    )
    return {
        **invitation,
        "token": raw_token,
        "invite_url": f"/join?token={raw_token}",
        "subteam_name": subteam.get("name", ""),
    }
