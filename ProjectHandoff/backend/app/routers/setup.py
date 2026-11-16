from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/setup", tags=["setup"])


class DriveClientIn(BaseModel):
    """Google OAuth client credentials, entered once in the first-run wizard."""

    client_id: str = Field(min_length=10, max_length=300)
    client_secret: str = Field(min_length=8, max_length=300)
    redirect_uri: str = Field(default="", max_length=300)


def _client_file(settings) -> Path:
    # Lives next to the OAuth token file (.tokens/, gitignored).
    return Path(settings.google_token_file).parent / "oauth_client.json"


@router.get("/status")
async def setup_status(request: Request) -> dict:
    """Public first-run status: what (if anything) still needs setting up."""
    settings = request.app.state.settings
    backend = request.app.state.backend
    client_configured = settings.drive_configured
    authorized = backend.mode == "drive" and backend.token_file_exists()
    return {
        "storage_mode": backend.mode,
        "client_configured": client_configured,
        "authorized": authorized,
        "needs_setup": backend.mode == "drive" and not authorized,
        # Public by nature (registered in the Google Cloud console), shown in
        # the wizard so the organizer knows exactly what to paste there.
        "redirect_uri": settings.google_oauth_redirect_uri,
    }


@router.post("/drive-client", status_code=201)
async def configure_drive_client(payload: DriveClientIn, request: Request) -> dict:
    """First-run only: store the Google OAuth client credentials server-side.

    Deliberately locked to unconfigured deployments — once a client exists
    (wizard, .env or Google secret file), this endpoint refuses to run so a
    stray request can never replace the deployment's credentials. Rotating
    credentials is a deliberate operator action (delete the stored file).
    """
    settings = request.app.state.settings
    backend = request.app.state.backend
    if backend.mode != "drive":
        raise HTTPException(
            status_code=400,
            detail="Drive setup is only needed when the backend runs in Google Drive mode (PH_STORAGE_MODE=drive).",
        )
    if settings.drive_configured:
        raise HTTPException(
            status_code=403,
            detail="A Google OAuth client is already configured on this deployment. "
            "To change it, remove the stored client file and restart.",
        )

    client_id = payload.client_id.strip()
    client_secret = payload.client_secret.strip()
    redirect_uri = payload.redirect_uri.strip() or settings.google_oauth_redirect_uri

    path = _client_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}),
        "utf-8",
    )
    os.replace(tmp, path)

    # Activate immediately in the running process (Settings instances are
    # mutable; backend and routers read the same object from app.state).
    settings.google_client_id = client_id
    settings.google_client_secret = client_secret
    settings.google_oauth_redirect_uri = redirect_uri
    return {"ok": True, "client_configured": True, "redirect_uri": redirect_uri}


def load_stored_client(settings) -> None:
    """Restore wizard-entered client credentials at startup (if present)."""
    path = _client_file(settings)
    if settings.drive_configured or not path.is_file():
        return
    try:
        data = json.loads(path.read_text("utf-8"))
        settings.google_client_id = str(data.get("client_id", ""))
        settings.google_client_secret = str(data.get("client_secret", ""))
        if data.get("redirect_uri"):
            settings.google_oauth_redirect_uri = str(data["redirect_uri"])
    except (ValueError, OSError):
        pass  # corrupt file — behave as unconfigured; the wizard can redo it
