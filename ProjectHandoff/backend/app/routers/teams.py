from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, SettingsDep, invalidate_user_cache, require_roles
from app.schemas.api import InviteCreateIn, MemberUpdateIn, TeamCreateIn, TeamUpdateIn
from app.security import hash_token
from app.services.activity import (
    ACTION_DRIVE_FOLDER_CONNECTED,
    ACTION_INVITE_CREATED,
    ACTION_INVITE_REVOKED,
    ACTION_MEMBER_LEFT,
    ACTION_ROLE_CHANGED,
    ACTION_TEAM_UPDATED,
    log_activity,
)
from app.services.csvstore import now_iso, new_id
from app.services.drive.base import DriveError, NotFoundError
from app.services.drive_link import drive_folder_url, extract_drive_folder_id

logger = logging.getLogger("projecthandoff")

router = APIRouter(prefix="/api/teams", tags=["teams"])
invitations_router = APIRouter(prefix="/api", tags=["invitations"])

INVITE_TTL_DAYS = 7


def _parse_drive_link(link: str) -> str:
    try:
        return extract_drive_folder_id(link)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _resolve_drive_folder(link: str, backend, require: bool = True) -> dict:
    """Turn a pasted Drive folder link into columns for the teams table.

    In drive mode the folder is verified through the connected account so
    broken links fail at setup, not on the first upload.
    """
    folder_id = _parse_drive_link(link)
    if not folder_id:
        if require:
            raise HTTPException(
                status_code=422,
                detail="A Google Drive folder link is required. Create a folder in Drive and paste its link here — every team file will be stored in it and shared with all members.",
            )
        return {"drive_folder_id": "", "drive_folder_url": ""}
    if backend.mode == "drive":
        try:
            info = await backend.folder_info(folder_id)
        except NotFoundError:
            raise HTTPException(
                status_code=400,
                detail="That Drive folder was not found. Check the link and make sure the connected organizer account can access it.",
            ) from None
        except DriveError as exc:
            raise HTTPException(status_code=400, detail=f"Could not verify the Drive folder: {exc}") from exc
        return {"drive_folder_id": info["id"], "drive_folder_url": info["url"]}
    # Local development mode: record the link without touching Drive.
    return {"drive_folder_id": folder_id, "drive_folder_url": drive_folder_url(folder_id)}


async def _share_with_member(backend, folder_id: str, email: str) -> bool:
    """Best-effort folder permission grant; returns True when it succeeded."""
    try:
        await backend.share_folder(folder_id, email)
        return True
    except DriveError as exc:
        logger.warning("Could not share the team Drive folder with %s: %s", email, exc)
        return False


@router.post("", status_code=201)
async def create_team(payload: TeamCreateIn, user: CurrentUser, db: DbDep, settings: SettingsDep) -> dict:
    if user.get("team_id"):
        raise HTTPException(status_code=409, detail="You already belong to a team")

    drive_cols = await _resolve_drive_folder(
        payload.drive_folder_url, db.backend, require=db.backend.mode == "drive"
    )

    team_id = new_id()
    team = {
        "team_id": team_id,
        "name": payload.name.strip(),
        "description": payload.description.strip(),
        "owner_id": user["user_id"],
        "created_at": now_iso(),
        "status": "active",
        **drive_cols,
    }

    def add_team(rows: list[dict]) -> list[dict]:
        rows.append(team)
        return rows

    def set_user(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user["user_id"]:
                row["team_id"] = team_id
                row["role"] = "owner"
                return rows
        raise HTTPException(status_code=404, detail="User not found")

    await db.mutate("teams", add_team)
    await db.mutate("users", set_user)
    if team["drive_folder_id"]:
        # Pin the folder *before* ensure_team so the team's CSVs and uploads
        # are created inside it from the very first write.
        await db.backend.set_team_root(team_id, team["drive_folder_id"])
    await db.ensure_team(team_id)
    invalidate_user_cache(user["user_id"])
    if team["drive_folder_id"]:
        await _share_with_member(db.backend, team["drive_folder_id"], user["email"])
        await log_activity(
            db, team_id=team_id, action=ACTION_DRIVE_FOLDER_CONNECTED,
            description=f"{user['name']} connected the team to a Google Drive folder — all team files now live there",
            user_id=user["user_id"],
        )
    await log_activity(
        db, team_id=team_id, action=ACTION_TEAM_UPDATED,
        description=f"{user['name']} created the team “{team['name']}”", user_id=user["user_id"],
    )
    return team


@router.get("/mine")
async def my_team(user: CurrentUser, db: DbDep) -> dict:
    team_id = user.get("team_id", "")
    if not team_id:
        return {"team": None, "members": []}
    teams = await db.query("teams")
    team = next((t for t in teams if t.get("team_id") == team_id), None)
    users = [u for u in await db.query("users") if u.get("team_id") == team_id]
    return {"team": team, "members": users}


@router.patch("/{team_id}")
async def update_team(team_id: str, payload: TeamUpdateIn, user: CurrentUser, db: DbDep, settings: SettingsDep) -> dict:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")

    drive_cols: dict | None = None
    if payload.drive_folder_url is not None:
        drive_cols = await _resolve_drive_folder(payload.drive_folder_url, db.backend, require=False)

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("team_id") == team_id:
                if payload.name is not None:
                    row["name"] = payload.name.strip()
                if payload.description is not None:
                    row["description"] = payload.description.strip()
                if drive_cols is not None:
                    row.update(drive_cols)
                return rows
        raise HTTPException(status_code=404, detail="Team not found")

    await db.mutate("teams", fn)
    if drive_cols is not None:
        await db.backend.set_team_root(team_id, drive_cols["drive_folder_id"])
        if drive_cols["drive_folder_id"]:
            members = [u for u in await db.query("users") if u.get("team_id") == team_id]
            for member in members:
                await _share_with_member(db.backend, drive_cols["drive_folder_id"], member.get("email", ""))
            await log_activity(
                db, team_id=team_id, action=ACTION_DRIVE_FOLDER_CONNECTED,
                description=f"{user['name']} connected the team to a Google Drive folder — shared with all {len(members)} members",
                user_id=user["user_id"],
            )
        else:
            await log_activity(
                db, team_id=team_id, action=ACTION_TEAM_UPDATED,
                description=f"{user['name']} unlinked the team's Google Drive folder", user_id=user["user_id"],
            )
    await log_activity(
        db, team_id=team_id, action=ACTION_TEAM_UPDATED,
        description=f"{user['name']} updated the team profile", user_id=user["user_id"],
    )
    teams = await db.query("teams")
    return next(t for t in teams if t.get("team_id") == team_id)


@router.get("/{team_id}/members")
async def list_members(team_id: str, user: CurrentUser, db: DbDep) -> list[dict]:
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    return [u for u in await db.query("users") if u.get("team_id") == team_id]


@router.patch("/{team_id}/members/{member_id}")
async def update_member(team_id: str, member_id: str, payload: MemberUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")

    users = await db.query("users")
    member = next((u for u in users if u.get("user_id") == member_id and u.get("team_id") == team_id), None)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get("role") == "owner":
        raise HTTPException(status_code=400, detail="The team owner's role cannot be changed")
    if payload.role == "owner":
        raise HTTPException(status_code=400, detail="Ownership cannot be assigned; transfer the team instead")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == member_id:
                if payload.role is not None:
                    row["role"] = payload.role
                if payload.status is not None:
                    row["status"] = payload.status
                return rows
        raise HTTPException(status_code=404, detail="Member not found")

    await db.mutate("users", fn)
    invalidate_user_cache(member_id)
    if payload.role is not None:
        await log_activity(
            db, team_id=team_id, action=ACTION_ROLE_CHANGED,
            description=f"{user['name']} set {member['name']}'s role to {payload.role}",
            user_id=user["user_id"],
        )
    return {**member, "role": payload.role or member["role"], "status": payload.status or member["status"]}


@router.delete("/{team_id}/members/{member_id}")
async def remove_member(team_id: str, member_id: str, user: CurrentUser, db: DbDep) -> dict:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if member_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from the team")

    users = await db.query("users")
    member = next((u for u in users if u.get("user_id") == member_id and u.get("team_id") == team_id), None)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get("role") == "owner":
        raise HTTPException(status_code=400, detail="The team owner cannot be removed")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == member_id:
                row["team_id"] = ""
                row["role"] = "member"
                return rows
        raise HTTPException(status_code=404, detail="Member not found")

    await db.mutate("users", fn)
    invalidate_user_cache(member_id)
    team = next((t for t in await db.query("teams") if t.get("team_id") == team_id), None)
    if team and team.get("drive_folder_id"):
        try:
            await db.backend.unshare_folder(team["drive_folder_id"], member["email"])
        except DriveError as exc:
            logger.warning("Could not revoke Drive folder access for %s: %s", member["email"], exc)
    await log_activity(
        db, team_id=team_id, action=ACTION_MEMBER_LEFT,
        description=f"{user['name']} removed {member['name']} from the team", user_id=user["user_id"],
    )
    return {"ok": True}


@router.post("/{team_id}/drive/share")
async def share_drive_folder(team_id: str, user: CurrentUser, db: DbDep) -> dict:
    """(Re)share the team's Drive folder with every active member."""
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")

    teams = await db.query("teams")
    team = next((t for t in teams if t.get("team_id") == team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    folder_id = team.get("drive_folder_id", "")
    if not folder_id:
        raise HTTPException(
            status_code=400,
            detail="No Drive folder is linked to this team yet. Add one from the team page first.",
        )
    members = [u for u in await db.query("users") if u.get("team_id") == team_id and u.get("status") == "active"]
    failed: list[str] = []
    shared = 0
    for member in members:
        if await _share_with_member(db.backend, folder_id, member.get("email", "")):
            shared += 1
        else:
            failed.append(member.get("email", ""))
    await log_activity(
        db, team_id=team_id, action=ACTION_DRIVE_FOLDER_CONNECTED,
        description=f"{user['name']} shared the team Drive folder with all members ({shared}/{len(members)} granted)",
        user_id=user["user_id"],
    )
    return {
        "shared": shared,
        "failed": failed,
        "members": len(members),
        "folder_url": team.get("drive_folder_url") or drive_folder_url(folder_id),
    }


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.post("/{team_id}/invitations", status_code=201)
async def create_invitation(team_id: str, payload: InviteCreateIn, user: CurrentUser, db: DbDep, settings: SettingsDep) -> dict:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")

    users = await db.query("users")
    if any(u.get("email", "").lower() == payload.email.lower() and u.get("team_id") == team_id for u in users):
        raise HTTPException(status_code=409, detail="This person is already a member of the team")

    raw_token = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)).isoformat()
    invitation = {
        "invitation_id": new_id(),
        "team_id": team_id,
        "email": payload.email.lower().strip(),
        "role": payload.role,
        "token_hash": hash_token(raw_token),
        "expires_at": expires_at,
        "status": "pending",
    }
    await db.insert("invitations", invitation)
    await log_activity(
        db, team_id=team_id, action=ACTION_INVITE_CREATED,
        description=f"{user['name']} invited {invitation['email']} as {payload.role}",
        user_id=user["user_id"],
    )
    return {**invitation, "token": raw_token, "invite_url": f"{settings.frontend_url}/join?token={raw_token}"}


@router.get("/{team_id}/invitations")
async def list_invitations(team_id: str, user: CurrentUser, db: DbDep) -> list[dict]:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    invites = [i for i in await db.query("invitations") if i.get("team_id") == team_id]
    # lazily expire stale invitations
    changed = False
    for inv in invites:
        if inv.get("status") == "pending" and inv.get("expires_at") and inv["expires_at"] < now_iso():
            inv["status"] = "expired"
            changed = True
    if changed:
        def fn(rows: list[dict]) -> list[dict]:
            for row in rows:
                match = next((i for i in invites if i["invitation_id"] == row.get("invitation_id")), None)
                if match is not None and match.get("status") == "expired":
                    row["status"] = "expired"
            return rows
        await db.mutate("invitations", fn)
    return invites


@router.post("/{team_id}/invitations/{invitation_id}/revoke")
async def revoke_invitation(team_id: str, invitation_id: str, user: CurrentUser, db: DbDep) -> dict:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("invitation_id") == invitation_id and row.get("team_id") == team_id:
                if row.get("status") != "pending":
                    raise HTTPException(status_code=400, detail="Only pending invitations can be revoked")
                row["status"] = "revoked"
                return rows
        raise HTTPException(status_code=404, detail="Invitation not found")

    await db.mutate("invitations", fn)
    await log_activity(
        db, team_id=team_id, action=ACTION_INVITE_REVOKED,
        description=f"{user['name']} revoked an invitation", user_id=user["user_id"],
    )
    return {"ok": True}


@invitations_router.get("/invitations/validate")
async def validate_invitation(token: str, db: DbDep) -> dict:
    token_hash = hash_token(token.strip())
    invites = await db.query("invitations")
    invite = next((i for i in invites if i.get("token_hash") == token_hash), None)
    if invite is None or invite.get("status") != "pending":
        raise HTTPException(status_code=400, detail="This invitation is invalid or has already been used")
    if invite.get("expires_at") and invite["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="This invitation has expired")
    teams = await db.query("teams")
    team = next((t for t in teams if t.get("team_id") == invite["team_id"]), None)
    if team is None:
        raise HTTPException(status_code=400, detail="The invited team no longer exists")
    return {"team_name": team["name"], "team_id": team["team_id"], "role": invite["role"], "email": invite["email"]}
