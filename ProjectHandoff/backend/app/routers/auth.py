from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, SettingsDep, invalidate_user_cache
from app.schemas.api import LoginIn, PasswordChangeIn, ProfileUpdateIn, RegisterIn
from app.security import create_token, hash_password, hash_token, verify_password
from app.services.activity import ACTION_MEMBER_JOINED
from app.services.csvstore import now_iso, new_id
from app.services.drive.base import DriveError

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
        await _log_join(db, team_id, user)
        folder_id = team.get("drive_folder_id", "") if team else ""
        if folder_id:
            # The team's Drive folder is open to every member: grant this
            # account writer access as soon as they join (best effort).
            try:
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


@router.get("/me")
async def me(user: CurrentUser, db: DbDep) -> dict:
    team = None
    if user.get("team_id"):
        teams = await db.query("teams")
        team = next((t for t in teams if t.get("team_id") == user["team_id"]), None)
    return {"user": user, "team": team}


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
