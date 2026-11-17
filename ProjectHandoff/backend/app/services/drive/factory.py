from __future__ import annotations

from app.config import Settings

from .base import DriveBackend
from .google_drive import GoogleDriveBackend
from .local import LocalDriveBackend


def create_drive_backend(settings: Settings) -> DriveBackend:
    """Resolve the storage backend from settings.

    Multi-tenant model: in drive mode each team connects its own Google
    account at team creation — no host-wide token is required to boot. An
    optional legacy host token (PH_GOOGLE_TOKEN_FILE) keeps single-organizer
    deployments working and holds the global registry. ``auto`` uses a host
    token when present, otherwise explicit local development storage.
    """
    mode = settings.storage_mode.strip().lower()

    if mode == "drive":
        return GoogleDriveBackend(settings)

    if mode == "local":
        if not settings.allow_local_storage:
            raise RuntimeError(
                "PH_STORAGE_MODE=local requires PH_ALLOW_LOCAL_STORAGE=true. "
                "Local storage is for development only."
            )
        return LocalDriveBackend(settings.local_data_dir)

    if mode == "auto":
        if GoogleDriveBackend(settings).token_file_exists():
            return GoogleDriveBackend(settings)
        if settings.allow_local_storage:
            return LocalDriveBackend(settings.local_data_dir)
        raise RuntimeError(
            "No Google Drive OAuth token found and local storage is not enabled.\n"
            "  1. Set PH_STORAGE_MODE=drive (multi-tenant: teams connect their own Google accounts), or\n"
            "  2. Authorize a host account via Settings (PH_GOOGLE_CLIENT_ID / PH_GOOGLE_CLIENT_SECRET), or\n"
            "  3. Explicitly set PH_STORAGE_MODE=local AND PH_ALLOW_LOCAL_STORAGE=true for development."
        )

    raise RuntimeError(f"Unknown PH_STORAGE_MODE: {settings.storage_mode!r} (expected auto|drive|local)")
