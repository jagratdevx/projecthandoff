from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ProjectHandoff/ root — anchors cwd-relative defaults so the app behaves the same
# no matter which directory uvicorn is launched from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings, loaded from environment variables prefixed with PH_.

    Also reads ProjectHandoff/.env (or backend/../.env when run from backend/).
    """

    model_config = SettingsConfigDict(
        env_prefix="PH_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Security
    secret_key: str = "dev-insecure-secret-change-me"
    token_ttl_hours: int = 168

    # Storage: auto | drive | local
    storage_mode: str = "auto"
    allow_local_storage: bool = False
    local_data_dir: str = str(PROJECT_ROOT / "data")

    # Google OAuth (organizer account authorizes the backend)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/drive/oauth/callback"
    google_token_file: str = str(PROJECT_ROOT / ".tokens" / "token.json")

    # Google Drive layout
    drive_root_folder_id: str = ""
    drive_root_folder_name: str = "ProjectHandoff"
    # Hard ceiling for one Drive HTTP call — a stalled connection must never
    # hold the backend's I/O queue (and the whole app) hostage.
    drive_timeout_seconds: int = 30

    # Uploads
    max_upload_mb: int = 10
    allowed_extensions: str = "pdf,doc,docx,xls,xlsx,ppt,pptx,csv,txt,md,png,jpg,jpeg,gif,webp,zip"

    # CORS / URLs
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    frontend_url: str = "http://localhost:5173"

    # Backups
    backup_retention: int = 20

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @cached_property
    def allowed_ext_set(self) -> frozenset[str]:
        return frozenset(
            e.strip().lower().lstrip(".")
            for e in self.allowed_extensions.split(",")
            if e.strip()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def drive_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)
