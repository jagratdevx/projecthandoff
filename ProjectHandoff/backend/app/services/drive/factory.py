from __future__ import annotations

from app.config import Settings

from .base import DriveBackend
from .google_drive import GoogleDriveBackend
from .local import LocalDriveBackend


def create_drive_backend(settings: Settings) -> DriveBackend:
    """Resolve the storage backend from settings.

    Never silently falls back: with PH_STORAGE_MODE=auto, Drive is used when an
    OAuth token file exists; otherwise start-up fails with instructions unless
    the operator explicitly opted into local development storage.
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
            "  1. Set PH_GOOGLE_CLIENT_ID / PH_GOOGLE_CLIENT_SECRET in ProjectHandoff/.env\n"
            "  2. Start the backend and open the Settings page to authorize Drive, or\n"
            "  3. Explicitly set PH_STORAGE_MODE=local AND PH_ALLOW_LOCAL_STORAGE=true for development."
        )

    raise RuntimeError(f"Unknown PH_STORAGE_MODE: {settings.storage_mode!r} (expected auto|drive|local)")
