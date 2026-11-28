from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.security import verify_token
from app.services.csvstore import CsvStore
from app.services.subteams import has_full_access

_bearer = HTTPBearer(auto_error=False)

_USER_CACHE_TTL = 5.0  # seconds; users.csv is re-verified against Drive at most this often
_user_cache: dict[str, tuple[float, dict]] = {}


def invalidate_user_cache(user_id: str | None = None) -> None:
    if user_id is None:
        _user_cache.clear()
    else:
        _user_cache.pop(user_id, None)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> CsvStore:
    return request.app.state.db


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[CsvStore, Depends(get_db)]


async def load_user(db: CsvStore, user_id: str) -> dict | None:
    """Load a user row with a short TTL cache (Drive reads are expensive)."""
    cached = _user_cache.get(user_id)
    now = time.monotonic()
    if cached and now - cached[0] < _USER_CACHE_TTL:
        return cached[1]
    rows = await db.query("users")
    user = next((r for r in rows if r.get("user_id") == user_id), None)
    if user is not None:
        _user_cache[user_id] = (now, user)
    else:
        invalidate_user_cache(user_id)
    return user


async def get_current_user(
    request: Request,
    db: DbDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Authenticate the session token and re-validate the user against users.csv.

    The frontend-supplied user/team/role in the token is never trusted on its
    own — the live users.csv row is authoritative for status/team/role.
    """
    settings: Settings = request.app.state.settings
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    claims = verify_token(credentials.credentials, settings.secret_key)
    if claims is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    user = await load_user(db, claims.get("sub", ""))
    if user is None or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="Account is inactive or no longer exists")
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]


def require_team(user: dict) -> str:
    team_id = user.get("team_id", "")
    if not team_id:
        raise HTTPException(
            status_code=409,
            detail="You are not part of a team yet. Create or join a team first.",
        )
    return team_id


def require_roles(user: dict, *roles: str) -> dict:
    if not has_full_access(user) and user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions for this action")
    return user


def require_full_access(user: dict) -> dict:
    if not has_full_access(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions for this action")
    return user


def require_exact_roles(user: dict, *roles: str) -> dict:
    if user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions for this action")
    return user


def ensure_team_access(resource_team: str, user: dict) -> None:
    """Team-level data isolation: the resource's team must match the caller's."""
    team_id = require_team(user)
    if resource_team != team_id:
        raise HTTPException(status_code=404, detail="Resource not found in your team")
