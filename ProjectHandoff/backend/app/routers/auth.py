from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, SettingsDep, invalidate_user_cache
from app.schemas.api import (
    AccountResetIn, InviteAcceptIn, LoginIn, PasswordChangeIn, ProfileUpdateIn, RegisterIn,
)
from app.security import create_token, hash_password, hash_token, verify_password
from app.services.activity import ACTION_MEMBER_JOINED
from app.services.csvstore import now_iso, new_id
from app.services.drive.base import DriveError
from app.services.memberships import (
    active_memberships as active_team_memberships,
    add_team_membership as add_membership_record,
    memberships_for_user as team_memberships_for_user,
    set_current_membership,
)
from app.services.subteams import add_membership, get_subteam, memberships_for

import logging

logger = logging.getLogger("projecthandoff")

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _make_token(settings: SettingsDep, user: dict) -> str:
    return create_token(
        {
            "sub": user["user_id"],
            "team": user.get("team_id", ""),
            "role": user.get("role", "member"),
            "iat": int(time.time()),
            "exp": int(time.time()) + settings.token_ttl_hours * 3600,
        },
        settings.secret_key,
    )


@router.post("/register", status_code=201)
async def register(payload: RegisterIn, db: DbDep, settings: SettingsDep) -> dict:
    email = payload.email.lower().strip()

    users = await db.query("users")
    if any(u.get("email", "").lower() == email for u in users):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    team_id, role = "", "member"
    subteam_id, subteam_role = "", "volunteer"
    if payload.invite_token:
        invites = await db.query("invitations")
        token_hash = hash_token(payload.invite_token.strip())
        invite = next(
            (i for i in invites if i.get("token_hash") == token_hash and i.get("status") == "pending"),
            None,
        )
        if invite is None:
            raise HTTPException(status_code=400, detail="This invitation is invalid or has already been used")
        if invite.get("expires_at") and invite["expires_at"] < now_iso():
            raise HTTPException(status_code=400, detail="This invitation has expired")
        if invite.get("email", "").lower() != email:
            raise HTTPException(status_code=400, detail="This invitation was issued for a different email address")
        teams = await db.query("teams")
        team = next((t for t in teams if t.get("team_id") == invite["team_id"] and t.get("status") == "active"), None)
        if team is None:
            raise HTTPException(status_code=400, detail="The invited team no longer exists")
        team_id, role = invite["team_id"], invite["role"]
        subteam_id = invite.get("subteam_id", "")
        subteam_role = invite.get("subteam_role", "") or "volunteer"
        if subteam_id and await get_subteam(db, team_id, subteam_id) is None:
            raise HTTPException(status_code=400, detail="This invitation points to a subteam that no longer exists")

        def consume(rows: list[dict]) -> list[dict]:
            for row in rows:
                if row.get("invitation_id") == invite["invitation_id"]:
                    row["status"] = "accepted"
            return rows

        await db.mutate("invitations", consume)

    user_id = new_id()
    user = {
        "user_id": user_id,
        "name": payload.name.strip(),
        "email": email,
        "role": role,
        "team_id": team_id,
        "joined_at": now_iso(),
        "status": "active",
    }

    def add_user(rows: list[dict]) -> list[dict]:
        rows.append(user)
        return rows

    await db.mutate("users", add_user)
    await db.insert(
        "credentials",
        {"user_id": user_id, "password_hash": hash_password(payload.password), "created_at": now_iso()},
    )
    if team_id:
        await db.ensure_team(team_id)
        is_current = not await active_team_memberships(db, user_id)
        await add_membership_record(
            db, user_id=user_id, team_id=team_id, email=email,
            role=role, state="active", is_current=is_current,
        )
        if is_current:
            await set_current_membership(db, user_id, team_id)
        if subteam_id:
            await add_membership(db, team_id, subteam_id, user_id, subteam_role, "")
        await _log_join(db, team_id, user)
        from app.services.drive.google_drive import GoogleDriveBackend

        folder_id = team.get("drive_folder_id", "") if team else ""
        if folder_id:
            # The team's Drive folder is open to every member: grant this
            # account writer access as soon as they join (best effort, via
            # the team's own connected Google account).
            try:
                if isinstance(db.backend, GoogleDriveBackend):
                    await db.backend.team_share_folder(team_id, folder_id, email)
                else:
                    await db.backend.share_folder(folder_id, email)
            except DriveError as exc:
                logger.warning(
                    "Could not share the team Drive folder with %s: %s", email, exc
                )
    invalidate_user_cache(user_id)

    return {"token": _make_token(settings, user), "user": user}


async def _log_join(db: DbDep, team_id: str, user: dict) -> None:
    from app.services.activity import log_activity

    await log_activity(
        db,
        team_id=team_id,
        action=ACTION_MEMBER_JOINED,
        description=f"{user['name']} joined the team",
        user_id=user["user_id"],
    )


@router.post("/login")
async def login(payload: LoginIn, db: DbDep, settings: SettingsDep) -> dict:
    users = await db.query("users")
    user = next((u for u in users if u.get("email", "").lower() == payload.email.lower().strip()), None)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    creds = await db.query("credentials")
    cred = next((c for c in creds if c.get("user_id") == user["user_id"]), None)
    if cred is None or not verify_password(payload.password, cred.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="This account is inactive")
    return {"token": _make_token(settings, user), "user": user}


@router.post("/invitations/accept")
async def accept_invitation(payload: InviteAcceptIn, user: CurrentUser, db: DbDep) -> dict:
    """Let an existing account use a team/subteam invite link without re-registering."""
    email = user.get("email", "").lower().strip()
    token_hash = hash_token(payload.invite_token.strip())
    invites = await db.query("invitations")
    invite = next(
        (i for i in invites if i.get("token_hash") == token_hash and i.get("status") == "pending"),
        None,
    )
    if invite is None:
        raise HTTPException(status_code=400, detail="This invitation is invalid or has already been used")
    if invite.get("expires_at") and invite["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="This invitation has expired")
    if invite.get("email", "").lower() != email:
        raise HTTPException(status_code=400, detail="This invitation was issued for a different email address")

    team_id = invite["team_id"]
    teams = await db.query("teams")
    if not any(t.get("team_id") == team_id and t.get("status") == "active" for t in teams):
        raise HTTPException(status_code=400, detail="The invited team no longer exists")
    active = await active_team_memberships(db, user["user_id"])
    if active and any(row.get("team_id") != team_id for row in active):
        raise HTTPException(status_code=409, detail="You already belong to a different active team")
    joining_new_team = not active

    subteam_id = invite.get("subteam_id", "")
    subteam_role = invite.get("subteam_role", "") or "volunteer"
    if subteam_id and await get_subteam(db, team_id, subteam_id) is None:
        raise HTTPException(status_code=400, detail="This invitation points to a subteam that no longer exists")

    def consume(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("invitation_id") == invite["invitation_id"]:
                row["status"] = "accepted"
        return rows

    await db.mutate("invitations", consume)
    if joining_new_team:
        def join_team(rows: list[dict]) -> list[dict]:
            for row in rows:
                if row.get("user_id") == user["user_id"]:
                    row["team_id"] = team_id
                    row["role"] = invite.get("role", "member")
            return rows

        await db.mutate("users", join_team)
        invalidate_user_cache(user["user_id"])
    await add_membership_record(
        db, user_id=user["user_id"], team_id=team_id, email=email,
        role=invite.get("role", "member"), state="active",
        is_current=joining_new_team,
    )
    if joining_new_team:
        await set_current_membership(db, user["user_id"], team_id)
    if subteam_id:
        await add_membership(db, team_id, subteam_id, user["user_id"], subteam_role, "")
    await _log_join(db, team_id, user)
    return {"ok": True, "team_id": team_id, "subteam_id": subteam_id}


@router.post("/account/reset")
async def reset_account(payload: AccountResetIn, user: CurrentUser, db: DbDep) -> dict:
    """Recovery path: detach an account from all teams without deleting its history."""
    if payload.email.lower().strip() != user.get("email", "").lower().strip():
        raise HTTPException(status_code=400, detail="The email does not match this account")
    if not payload.confirm:
        raise HTTPException(status_code=422, detail="Account reset must be confirmed")

    team_id = user.get("team_id", "")
    if team_id and user.get("role") in ("owner", "teacher"):
        teams = {t.get("team_id", ""): t for t in await db.query("teams")}
        if teams.get(team_id, {}).get("status") == "active":
            overseers = [
                u for u in await db.query("users")
                if u.get("team_id") == team_id and u.get("role") in ("owner", "teacher")
            ]
            if len(overseers) <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Complete the team or assign another overseer before resetting this account",
                )

    def detach(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user["user_id"]:
                row["team_id"] = ""
                row["role"] = "member"
        return rows

    def remove_memberships(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user["user_id"]:
                row["state"] = "removed"
                row["is_current"] = "0"
        return rows

    await db.mutate("users", detach)
    await db.mutate("team_memberships", remove_memberships)
    invalidate_user_cache(user["user_id"])
    return {"ok": True, "team_id": ""}


@router.get("/me")
async def me(user: CurrentUser, db: DbDep) -> dict:
    team = None
    subteams = []
    if user.get("team_id"):
        teams = await db.query("teams")
        team = next((t for t in teams if t.get("team_id") == user["team_id"]), None)
        memberships = await memberships_for(db, user["team_id"], user["user_id"])
        if memberships:
            names = {row["subteam_id"]: row.get("name", "") for row in await db.query("subteams", user["team_id"])}
            subteams = [
                {"subteam_id": sid, "name": names.get(sid, ""), "role": role}
                for sid, role in sorted(memberships.items(), key=lambda item: names.get(item[0], "").casefold())
            ]
    all_teams = await db.query("teams")
    team_names = {t.get("team_id", ""): t for t in all_teams}
    memberships = await team_memberships_for_user(db, user["user_id"])
    team_rows = []
    for item in memberships:
        team_info = team_names.get(item.get("team_id", ""))
        if team_info is None or item.get("state") == "removed":
            continue
        team_rows.append({
            "team_id": item["team_id"],
            "name": team_info.get("name", ""),
            "description": team_info.get("description", ""),
            "status": team_info.get("status", ""),
            "role": item.get("role", ""),
            "state": item.get("state", ""),
            "is_current": item.get("is_current") == "1",
            "joined_at": item.get("joined_at", ""),
        })
    can_create_team = not await active_team_memberships(db, user["user_id"])
    return {
        "user": user,
        "team": team,
        "subteams": subteams,
        "teams": team_rows,
        "can_create_team": can_create_team,
    }


@router.patch("/me")
async def update_me(payload: ProfileUpdateIn, user: CurrentUser, db: DbDep) -> dict:
    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user["user_id"]:
                row["name"] = payload.name.strip()
                return rows
        raise HTTPException(status_code=404, detail="User not found")

    await db.mutate("users", fn)
    invalidate_user_cache(user["user_id"])
    return {"user": {**user, "name": payload.name.strip()}}


@router.post("/password")
async def change_password(payload: PasswordChangeIn, user: CurrentUser, db: DbDep) -> dict:
    creds = await db.query("credentials")
    cred = next((c for c in creds if c.get("user_id") == user["user_id"]), None)
    if cred is None or not verify_password(payload.current_password, cred.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user["user_id"]:
                row["password_hash"] = hash_password(payload.new_password)
                return rows
        raise HTTPException(status_code=404, detail="Credential row missing")

    await db.mutate("credentials", fn)
    return {"ok": True}
