from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.deps import (
    CurrentUser, DbDep, SettingsDep, invalidate_user_cache,
    require_exact_roles, require_roles,
)
from app.schemas.api import (
    AccountResetIn,
    InviteCreateIn,
    MemberUpdateIn,
    TeamCompleteIn,
    TeamCreateIn,
    TeamDriveConnectIn,
    TeamDriveFolderIn,
    TeamUpdateIn,
)
from app.security import create_signed_state, hash_token, read_signed_state
from app.services.activity import (
    ACTION_DRIVE_FOLDER_CONNECTED,
    ACTION_INVITE_CREATED,
    ACTION_INVITE_REVOKED,
    ACTION_MEMBER_LEFT,
    ACTION_ROLE_CHANGED,
    ACTION_TEAM_UPDATED,
    ACTION_TEAM_COMPLETED,
    log_activity,
)
from app.services.csvstore import now_iso, new_id
from app.services.drive.base import DriveError, NotFoundError
from app.services.drive.google_drive import GoogleDriveBackend
from app.services.drive_link import drive_folder_url, extract_drive_folder_id
from app.services.memberships import (
    active_memberships,
    add_team_membership,
    mark_team_observed,
    memberships_for_user,
    remove_team_membership,
    set_current_membership,
    set_membership_role,
    set_membership_state,
)
from app.services.subteams import get_subteam

logger = logging.getLogger("projecthandoff")

router = APIRouter(prefix="/api/teams", tags=["teams"])
invitations_router = APIRouter(prefix="/api", tags=["invitations"])

INVITE_TTL_DAYS = 7

# Team-scoped CSV tables (everything that moves into the team's Drive folder)
TEAM_TABLES = (
    "projects", "events", "departments", "department_members", "subteams",
    "subteam_members", "subteam_activity",
    "tasks", "handovers", "comments", "attachments",
)


def _drive_backend(backend) -> GoogleDriveBackend:
    if not isinstance(backend, GoogleDriveBackend):
        raise HTTPException(
            status_code=400,
            detail="Google Drive is not active on this deployment (local development mode stores data on the server).",
        )
    return backend


def _parse_drive_link(link: str) -> str:
    try:
        return extract_drive_folder_id(link)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _resolve_drive_folder(link: str, backend, team_id: str = "") -> dict:
    """Turn a pasted Drive folder link into columns for the teams table.

    In drive mode the folder is verified through the TEAM's connected account
    so broken links fail at link time, not on the first upload.
    """
    folder_id = _parse_drive_link(link)
    if not folder_id:
        return {"drive_folder_id": "", "drive_folder_url": ""}
    if backend.mode == "drive":
        try:
            info = await backend.team_folder_info(team_id, folder_id)
        except NotFoundError:
            raise HTTPException(
                status_code=400,
                detail="That Drive folder was not found. Check the link and make sure the team's connected Google account can access it.",
            ) from None
        except DriveError as exc:
            raise HTTPException(status_code=400, detail=f"Could not verify the Drive folder: {exc}") from exc
        return {"drive_folder_id": info["id"], "drive_folder_url": info["url"]}
    # Local development mode: record the link without touching Drive.
    return {"drive_folder_id": folder_id, "drive_folder_url": drive_folder_url(folder_id)}


async def _share_with_member(backend, team_id: str, folder_id: str, email: str) -> bool:
    """Best-effort folder permission grant via the team's account."""
    if not email or not folder_id:
        return False
    try:
        if isinstance(backend, GoogleDriveBackend):
            await backend.team_share_folder(team_id, folder_id, email)
        else:
            await backend.share_folder(folder_id, email)
        return True
    except DriveError as exc:
        logger.warning("Could not share the team Drive folder with %s: %s", email, exc)
        return False


def _folder_key_for(project_id: str, event_id: str) -> str:
    if project_id:
        return f"Projects/{project_id}/files"
    if event_id:
        return f"Events/{event_id}/files"
    return "files"


async def _migrate_team_data_into_folder(db: DbDep, team_id: str, folder_id: str) -> None:
    """Move a team's staged/legacy data into its newly-linked Drive folder.

    Runs after the folder is verified but before it is pinned: rows are read
    from wherever they currently resolve (server disk staging or the legacy
    host account), then written into the team's own folder. Attachment files
    are re-uploaded so ``drive_file_id``s stay valid.
    """
    try:
        captured: dict[str, list[dict]] = {}
        attachment_bytes: dict[str, bytes] = {}
        for table in TEAM_TABLES:
            rows = await db.query(table, team_id)
            captured[table] = rows
        for attachment in captured.get("attachments", []):
            file_id = attachment.get("drive_file_id", "")
            if file_id:
                try:
                    attachment_bytes[file_id] = await db.backend.download_file(file_id, team_id)
                except DriveError as exc:
                    logger.warning("Could not read staged attachment %s: %s", file_id, exc)

        await db.backend.set_team_root(team_id, folder_id)

        for table, rows in captured.items():
            if not rows:
                continue

            def replace(_rows: list[dict], _captured: list[dict] = rows) -> list[dict]:
                return list(_captured)

            await db.mutate(table, replace, team_id)

        # Re-upload attachment files into the team's folder and repoint ids.
        for attachment in captured.get("attachments", []):
            data = attachment_bytes.get(attachment.get("drive_file_id", ""))
            if data is None:
                continue
            new_id_ = await db.backend.upload_file(
                f"TeamData/{team_id}/{_folder_key_for(attachment.get('project_id', ''), attachment.get('event_id', ''))}",
                attachment.get("file_name", "attachment"),
                data,
            )
            target_id = attachment["attachment_id"]

            def repoint(rows: list[dict], _tid: str = target_id, _fid: str = new_id_) -> list[dict]:
                for row in rows:
                    if row.get("attachment_id") == _tid:
                        row["drive_file_id"] = _fid
                return rows

            await db.mutate("attachments", repoint, team_id)
    except DriveError as exc:
        logger.error("Drive data migration for team %s failed: %s", team_id, exc)
        await log_activity(
            db, team_id=team_id, action=ACTION_DRIVE_FOLDER_CONNECTED,
            description=f"Drive folder connected, but migrating existing data into it failed: {exc}",
        )


@router.get("/drive/oauth/defaults")
async def team_drive_oauth_defaults(settings: SettingsDep) -> dict:
    """Public defaults for the create-team form's Google client fields."""
    return {"redirect_uri": settings.team_oauth_redirect_uri}


@router.get("/drive/oauth/callback")
async def team_drive_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    settings: SettingsDep = None,
):
    """Google redirects here after the team owner approves access.

    The code is exchanged with THIS team's stored client credentials and the
    token is saved per-team — the owner connects once and is never asked again
    (until they deliberately disconnect).
    """
    nonce = read_signed_state(state, settings.secret_key)
    fail = f"{settings.frontend_url}/team?drive=error"
    if error:
        return RedirectResponse(f"{fail}&reason=denied")
    if not state or nonce is None:
        return RedirectResponse(f"{fail}&reason=state")
    team_id, _, redirect_path = nonce.partition("|")
    if not code:
        return RedirectResponse(f"{fail}&reason=missing_code")

    backend = request.app.state.backend
    if not isinstance(backend, GoogleDriveBackend):
        return RedirectResponse(f"{fail}&reason=mode")

    await request.app.state.db.assert_writable(team_id)
    client = backend.team_client(team_id)
    if client is None:
        return RedirectResponse(f"{fail}&reason=no_client")

    # Duplicate callbacks happen (speculative pre-flights); the code is
    # single-use — if this team's token was just written, it's already done.
    if backend.team_token_exists(team_id) and request.app.state.backend._session_for_team(team_id).token_recently_written():
        return RedirectResponse(f"{settings.frontend_url}{redirect_path or '/team'}?drive=connected")

    redirect_uri = client.get("redirect_uri") or settings.google_oauth_redirect_uri
    try:
        payload = await backend.exchange_team_code(team_id, code, redirect_uri)
        await backend.save_team_token(team_id, payload)
    except DriveError as exc:
        logger.warning("Team OAuth exchange failed for %s: %s", team_id, exc)
        return RedirectResponse(f"{fail}&reason=exchange")

    return RedirectResponse(f"{settings.frontend_url}{redirect_path or '/team'}?drive=connected")


@router.post("/{team_id}/drive/connect", status_code=201)
async def connect_team_drive(team_id: str, payload: TeamDriveConnectIn, user: CurrentUser, db: DbDep, request: Request, settings: SettingsDep) -> dict:
    """Store the team's own Google OAuth client and return the consent URL.

    Step 1 of connecting a team's Drive (step 2 is the folder link). Once the
    owner approves, the token is remembered server-side — no repeated auth.
    """
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.assert_writable(team_id)
    backend = _drive_backend(db.backend)

    redirect_uri = payload.redirect_uri.strip() or settings.team_oauth_redirect_uri
    await backend.set_team_client(
        team_id, payload.client_id.strip(), payload.client_secret.strip(), redirect_uri,
    )
    state = create_signed_state(f"{team_id}|/team", settings.secret_key)
    try:
        authorize_url = await backend.team_authorize_url(team_id, state)
    except DriveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"authorize_url": authorize_url, "redirect_uri": redirect_uri}


@router.post("/{team_id}/drive/reconnect")
async def reconnect_team_drive(team_id: str, user: CurrentUser, db: DbDep, settings: SettingsDep) -> dict:
    """Consent URL for an already-configured team (token revoked/expired)."""
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    backend = _drive_backend(db.backend)
    if backend.team_client(team_id) is None:
        raise HTTPException(
            status_code=400,
            detail="This team has no Google client configured yet — connect Drive first.",
        )
    state = create_signed_state(f"{team_id}|/team", settings.secret_key)
    return {"authorize_url": await backend.team_authorize_url(team_id, state)}


@router.get("/{team_id}/drive/status")
async def team_drive_status(team_id: str, user: CurrentUser, db: DbDep) -> dict:
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    backend = db.backend
    teams = await db.query("teams")
    team = next((t for t in teams if t.get("team_id") == team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if not isinstance(backend, GoogleDriveBackend):
        return {
            "storage_mode": "local", "client_configured": False,
            "connected": False, "account": None, "folder": None,
        }
    status = await backend.team_status(team_id)
    folder = None
    if team.get("drive_folder_id"):
        folder = {
            "id": team["drive_folder_id"],
            "url": team.get("drive_folder_url") or drive_folder_url(team["drive_folder_id"]),
        }
    return {
        "storage_mode": "drive",
        "client_configured": backend.team_client(team_id) is not None,
        **status,
        "folder": folder,
    }


@router.post("/{team_id}/drive/folder", status_code=200)
async def link_team_drive_folder(team_id: str, payload: TeamDriveFolderIn, user: CurrentUser, db: DbDep) -> dict:
    """Verify + pin the team's shared Drive folder (step 2 of connecting).

    Everything the team stores lands in this folder from now on; existing
    staged data is migrated into it. Change the folder here any time — data
    moves with it.
    """
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.assert_writable(team_id)
    backend = db.backend
    if backend.mode == "drive":
        backend = _drive_backend(backend)
        if not backend.team_token_exists(team_id):
            raise HTTPException(
                status_code=409,
                detail="Connect Google Drive first (the owner approves access once from the team page), then link the folder.",
            )

    drive_cols = await _resolve_drive_folder(payload.drive_folder_url, backend, team_id=team_id)
    folder_id = drive_cols["drive_folder_id"]

    await db.mutate("teams", lambda rows: _set_folder(rows, team_id, drive_cols))
    if not folder_id:
        await db.backend.set_team_root(team_id, "")
        await log_activity(
            db, team_id=team_id, action=ACTION_TEAM_UPDATED,
            description=f"{user['name']} unlinked the team's Google Drive folder", user_id=user["user_id"],
        )
        teams = await db.query("teams")
        return next(t for t in teams if t.get("team_id") == team_id)

    await _migrate_team_data_into_folder(db, team_id, folder_id)

    members = [u for u in await db.query("users") if u.get("team_id") == team_id and u.get("status") == "active"]
    granted = 0
    for member in members:
        if await _share_with_member(backend, team_id, folder_id, member.get("email", "")):
            granted += 1
    await log_activity(
        db, team_id=team_id, action=ACTION_DRIVE_FOLDER_CONNECTED,
        description=f"{user['name']} linked the team's Google Drive folder — shared with {granted}/{len(members)} members",
        user_id=user["user_id"],
    )
    teams = await db.query("teams")
    return next(t for t in teams if t.get("team_id") == team_id)


def _set_folder(rows: list[dict], team_id: str, drive_cols: dict) -> list[dict]:
    for row in rows:
        if row.get("team_id") == team_id:
            row.update(drive_cols)
            return rows
    raise HTTPException(status_code=404, detail="Team not found")


@router.post("", status_code=201)
async def create_team(payload: TeamCreateIn, user: CurrentUser, db: DbDep, request: Request, settings: SettingsDep) -> dict:
    if await active_memberships(db, user["user_id"]):
        raise HTTPException(status_code=409, detail="You already belong to an active team")

    team_id = new_id()
    team = {
        "team_id": team_id,
        "name": payload.name.strip(),
        "description": payload.description.strip(),
        "owner_id": user["user_id"],
        "created_at": now_iso(),
        "status": "active",
        "drive_folder_id": "",
        "drive_folder_url": "",
    }

    authorize_url: str | None = None
    if db.backend.mode == "drive":
        backend = _drive_backend(db.backend)
        client_id = payload.drive_client_id.strip()
        client_secret = payload.drive_client_secret.strip()
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=422,
                detail="A Google OAuth client ID and secret are required to create a team — each team stores its data in its own Google Drive. Create one in your Google Cloud console (10 minutes, free) and paste it here.",
            )
        redirect_uri = payload.drive_redirect_uri.strip() or settings.team_oauth_redirect_uri
        await backend.set_team_client(team_id, client_id, client_secret, redirect_uri)
        state = create_signed_state(f"{team_id}|/team", settings.secret_key)
        authorize_url = await backend.team_authorize_url(team_id, state)

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
    await add_team_membership(
        db,
        user_id=user["user_id"], team_id=team_id, email=user.get("email", ""),
        role="owner", state="active", is_current=True,
    )
    await set_current_membership(db, user["user_id"], team_id)
    await db.ensure_team(team_id)
    invalidate_user_cache(user["user_id"])
    await log_activity(
        db, team_id=team_id, action=ACTION_TEAM_UPDATED,
        description=f"{user['name']} created the team “{team['name']}”", user_id=user["user_id"],
    )
    response = {**team}
    if authorize_url:
        # One-time Google consent for the team owner — members never see this.
        response["authorize_url"] = authorize_url
        response["next_step"] = "authorize_drive"
    return response


@router.get("/mine")
async def my_team(user: CurrentUser, db: DbDep) -> dict:
    team_id = user.get("team_id", "")
    if not team_id:
        return {"team": None, "members": []}
    teams = await db.query("teams")
    team = next((t for t in teams if t.get("team_id") == team_id), None)
    users = [u for u in await db.query("users") if u.get("team_id") == team_id]
    return {"team": team, "members": users}


@router.get("/memories")
async def team_memories(user: CurrentUser, db: DbDep) -> list[dict]:
    rows = await memberships_for_user(db, user["user_id"])
    teams = {t.get("team_id", ""): t for t in await db.query("teams")}
    result = []
    for row in rows:
        team = teams.get(row.get("team_id", ""))
        if not team or team.get("status") != "archived" or row.get("state") == "removed":
            continue
        result.append({
            "team_id": row["team_id"],
            "name": team.get("name", ""),
            "description": team.get("description", ""),
            "role": row.get("role", ""),
            "state": row.get("state", ""),
            "is_current": row.get("is_current") == "1",
            "joined_at": row.get("joined_at", ""),
        })
    return result


@router.post("/{team_id}/switch")
async def switch_team(team_id: str, user: CurrentUser, db: DbDep) -> dict:
    membership = next(
        (m for m in await memberships_for_user(db, user["user_id"]) if m.get("team_id") == team_id),
        None,
    )
    if membership is None or membership.get("state") == "removed":
        raise HTTPException(status_code=404, detail="You are not a member of that team")

    def set_user(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user["user_id"]:
                row["team_id"] = team_id
                row["role"] = membership.get("role", "member")
        return rows

    await db.mutate("users", set_user)
    await set_current_membership(db, user["user_id"], team_id)
    invalidate_user_cache(user["user_id"])
    team = next((t for t in await db.query("teams") if t.get("team_id") == team_id), None)
    return {"ok": True, "team": team, "state": membership.get("state", "active")}


@router.post("/{team_id}/complete")
async def complete_team(
    team_id: str, payload: TeamCompleteIn, user: CurrentUser, db: DbDep
) -> dict:
    require_exact_roles(user, "owner", "teacher")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    teams = await db.query("teams")
    team = next((t for t in teams if t.get("team_id") == team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.get("status") == "archived":
        return {"ok": True, "already_archived": True, "drive_failures": []}

    def expire_invites(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("team_id") == team_id and row.get("status") == "pending":
                row["status"] = "expired"
        return rows

    await db.mutate("invitations", expire_invites)
    await log_activity(
        db, team_id=team_id, action=ACTION_TEAM_COMPLETED,
        description=f"{user['name']} completed the event “{team.get('name', '')}”",
        user_id=user["user_id"],
    )

    drive_failures: list[str] = []
    folder_id = team.get("drive_folder_id", "")
    if folder_id and isinstance(db.backend, GoogleDriveBackend):
        members = await memberships_for_user_self(db, team_id)
        for email in members:
            try:
                await db.backend.team_share_folder(team_id, folder_id, email, role="reader")
            except DriveError as exc:
                drive_failures.append(f"{email}: {exc}")
    if drive_failures and not payload.force:
        raise HTTPException(status_code=502, detail=f"Could not make Drive folders read-only: {'; '.join(drive_failures)}")

    await mark_team_observed(db, team_id)

    def archive(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("team_id") == team_id:
                row["status"] = "archived"
        return rows

    await db.mutate("teams", archive)
    for member in await db.query("users"):
        if member.get("team_id") == team_id:
            invalidate_user_cache(member.get("user_id", ""))
    return {
        "ok": True,
        "already_archived": False,
        "drive_failures": drive_failures,
    }


async def memberships_for_user_self(db: DbDep, team_id: str) -> list[str]:
    emails = [
        row.get("email", "")
        for row in await db.query("team_memberships")
        if row.get("team_id") == team_id and row.get("state") != "removed" and row.get("email", "")
    ]
    return emails


@router.patch("/{team_id}")
async def update_team(team_id: str, payload: TeamUpdateIn, user: CurrentUser, db: DbDep, settings: SettingsDep) -> dict:
    require_roles(user, "owner", "admin")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")

    if payload.drive_folder_url is not None:
        # Folder changes go through the link endpoint, which verifies the
        # folder and migrates data; a bare PATCH would silently break paths.
        link = await link_team_drive_folder(
            team_id, TeamDriveFolderIn(drive_folder_url=payload.drive_folder_url), user, db,
        )
        if payload.name is None and payload.description is None:
            return link

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("team_id") == team_id:
                if payload.name is not None:
                    row["name"] = payload.name.strip()
                if payload.description is not None:
                    row["description"] = payload.description.strip()
                return rows
        raise HTTPException(status_code=404, detail="Team not found")

    await db.mutate("teams", fn)
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
    if payload.role is not None:
        await set_membership_role(db, member_id, team_id, payload.role)
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
    await remove_team_membership(db, member_id, team_id)
    invalidate_user_cache(member_id)
    await db.assert_writable(team_id)
    team = next((t for t in await db.query("teams") if t.get("team_id") == team_id), None)
    if team and team.get("drive_folder_id"):
        try:
            if isinstance(db.backend, GoogleDriveBackend):
                await db.backend.team_unshare_folder(team_id, team["drive_folder_id"], member["email"])
            else:
                await db.backend.unshare_folder(team["drive_folder_id"], member["email"])
        except DriveError as exc:
            logger.warning("Could not revoke Drive folder access for %s: %s", member["email"], exc)
    await log_activity(
        db, team_id=team_id, action=ACTION_MEMBER_LEFT,
        description=f"{user['name']} removed {member['name']} from the team", user_id=user["user_id"],
    )
    return {"ok": True}


@router.post("/{team_id}/members/{member_id}/reset")
async def reset_member(
    team_id: str, member_id: str, payload: AccountResetIn, user: CurrentUser, db: DbDep
) -> dict:
    require_exact_roles(user, "owner", "teacher")
    if user.get("team_id") != team_id:
        raise HTTPException(status_code=404, detail="Team not found")
    if not payload.confirm:
        raise HTTPException(status_code=422, detail="Account reset must be confirmed")
    people = await db.query("users")
    member = next(
        (u for u in people if u.get("user_id") == member_id and u.get("team_id") == team_id),
        None,
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if payload.email.lower().strip() != member.get("email", "").lower().strip():
        raise HTTPException(status_code=400, detail="The email does not match that member")
    if member.get("role") == "owner":
        raise HTTPException(status_code=400, detail="The team owner cannot be reset this way")

    def detach(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == member_id:
                row["team_id"] = ""
                row["role"] = "member"
        return rows

    await db.mutate("users", detach)
    await remove_team_membership(db, member_id, team_id)
    await set_membership_state(db, member_id, team_id, "removed")
    invalidate_user_cache(member_id)
    await log_activity(
        db, team_id=team_id, action=ACTION_ROLE_CHANGED,
        description=f"{user['name']} reset {member['name']}'s account", user_id=user["user_id"],
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
        if await _share_with_member(db.backend, team_id, folder_id, member.get("email", "")):
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
    if payload.subteam_id and await get_subteam(db, team_id, payload.subteam_id) is None:
        raise HTTPException(status_code=400, detail="That subteam does not belong to your team")

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
        "subteam_id": payload.subteam_id,
        "subteam_role": payload.subteam_role,
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
    if team.get("status") != "active":
        raise HTTPException(status_code=400, detail="This team's event is complete; invite links are no longer active")
    result = {"team_name": team["name"], "team_id": team["team_id"], "role": invite["role"], "email": invite["email"]}
    subteam_id = invite.get("subteam_id", "")
    if subteam_id:
        subteam = await get_subteam(db, team["team_id"], subteam_id)
        if subteam is None:
            raise HTTPException(status_code=400, detail="This invitation points to a subteam that no longer exists")
        result.update({
            "subteam_id": subteam_id,
            "subteam_name": subteam.get("name", ""),
            "subteam_role": invite.get("subteam_role", "volunteer"),
        })
    return result
