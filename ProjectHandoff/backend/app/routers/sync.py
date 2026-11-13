from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.deps import CurrentUser, SettingsDep, require_roles
from app.security import create_signed_state, verify_signed_state
from app.services.csvstore import now_iso
from app.services.drive.google_drive import GoogleDriveBackend

router = APIRouter(prefix="/api", tags=["sync"])

OAUTH_SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_EXCHANGE_URL = "https://oauth2.googleapis.com/token"


@router.get("/sync/status")
async def sync_status(request: Request) -> dict:
    """Lightweight poll target for the frontend's 10–15s sync loop."""
    backend = request.app.state.backend
    return {
        "server_time": now_iso(),
        "storage_mode": backend.mode,
        "note": "local" if backend.mode == "local"
        else "Google Drive (organizer account)",
    }


@router.get("/drive/status")
async def drive_status(request: Request, settings: SettingsDep) -> dict:
    backend = request.app.state.backend
    if backend.mode != "drive":
        return {
            "storage_mode": backend.mode,
            "drive_configured": settings.drive_configured,
            "authorized": False,
            "account": None,
            "message": "Backend runs in explicit local development mode; "
            "Google Drive is not used for persistence.",
        }
    status = await backend.status()
    return {
        "storage_mode": "drive",
        "drive_configured": settings.drive_configured,
        **status,
        "authorize_url": None if status.get("authorized") else "/api/drive/oauth/start",
    }


@router.get("/drive/oauth/start")
async def oauth_start(settings: SettingsDep, request: Request, frontend_redirect: str = "/settings"):
    """Return the Google authorization URL (organizer-only flow)."""
    if not settings.drive_configured:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured. Set PH_GOOGLE_CLIENT_ID and PH_GOOGLE_CLIENT_SECRET.",
        )
    state = create_signed_state(f"{frontend_redirect}|{request.url.netloc}", settings.secret_key)
    from urllib.parse import urlencode

    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })
    return {"authorize_url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@router.get("/drive/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    settings: SettingsDep = None,
):
    if error:
        return RedirectResponse(f"{settings.frontend_url}/settings?drive=error")
    if not state or not verify_signed_state(state, settings.secret_key):
        return RedirectResponse(f"{settings.frontend_url}/settings?drive=error&reason=state")
    if not code:
        return RedirectResponse(f"{settings.frontend_url}/settings?drive=error&reason=missing_code")

    import json

    import httpx

    response = await httpx.AsyncClient().post(
        TOKEN_EXCHANGE_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if response.status_code != 200:
        return RedirectResponse(f"{settings.frontend_url}/settings?drive=error&reason=exchange")

    token_data = response.json()
    payload = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "scopes": (token_data.get("scope") or OAUTH_SCOPE).split() or [OAUTH_SCOPE],
    }
    backend = request.app.state.backend
    if isinstance(backend, GoogleDriveBackend):
        backend.save_oauth_token(payload)
    else:
        import pathlib

        path = pathlib.Path(settings.google_token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), "utf-8")

    return RedirectResponse(f"{settings.frontend_url}/settings?drive=connected")


@router.post("/drive/oauth/disconnect")
async def oauth_disconnect(request: Request, user: CurrentUser, settings: SettingsDep) -> dict:
    require_roles(user, "owner", "admin")
    backend = request.app.state.backend
    if backend.mode != "drive":
        raise HTTPException(status_code=400, detail="The backend is not running in Google Drive mode")
    removed = backend.delete_oauth_token()
    return {"ok": True, "removed": removed}
