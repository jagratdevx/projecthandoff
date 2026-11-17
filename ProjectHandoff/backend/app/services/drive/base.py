from __future__ import annotations

from abc import ABC, abstractmethod


class DriveError(Exception):
    """Base class for Google Drive backend errors."""


class DriveAuthError(DriveError):
    """OAuth token missing, expired beyond refresh, or access denied.

    The user (organizer) must re-authorize the backend through the OAuth flow.
    """


class DriveTransientError(DriveError):
    """Recoverable network / 5xx failure — safe to retry."""


class StaleRevision(DriveError):
    """Optimistic concurrency failure: the file changed since it was read."""


class NotFoundError(DriveError):
    """File or folder does not exist."""


class DriveBackend(ABC):
    """Virtual file-system interface over persistent storage.

    All structured application data lives in CSV files addressed by virtual
    paths such as ``TeamData/users.csv`` or ``TeamData/{team_id}/tasks.csv``.
    The Google Drive implementation maps these paths onto a folder hierarchy
    owned by the organizer account. A clearly-labelled local implementation is
    provided for development only.
    """

    mode: str = "abstract"

    @abstractmethod
    async def ensure_root(self) -> None:
        """Create the root folder structure if missing."""

    @abstractmethod
    async def ensure_folder(self, path: str) -> str:
        """Create every missing folder segment; return the leaf id/path."""

    @abstractmethod
    async def file_exists(self, path: str) -> bool: ...

    @abstractmethod
    async def read_file(self, path: str) -> tuple[str, str]:
        """Return (content, revision). Raise NotFoundError when missing."""

    @abstractmethod
    async def write_file(self, path: str, content: str, expected_revision: str | None = None) -> str:
        """Write content, returning the new revision.

        When ``expected_revision`` is provided (and not empty), the write must
        verify the stored file still carries that revision and raise
        StaleRevision otherwise — an optimistic-concurrency check, *not* an
        atomic compare-and-swap guarantee (Drive offers none), which is why
        writes are additionally serialized per CSV by the store layer.
        """

    @abstractmethod
    async def upload_file(self, folder_path: str, filename: str, data: bytes, mimetype: str = "application/octet-stream") -> str:
        """Upload a binary file into a folder; return its file id."""

    @abstractmethod
    async def download_file(self, file_id: str, team_id: str = "") -> bytes: ...

    @abstractmethod
    async def delete_file(self, file_id: str, team_id: str = "") -> None: ...

    @abstractmethod
    async def list_folder(self, path: str) -> list[dict]:
        """Return [{'id': ..., 'name': ...}, ...] for immediate children."""

    @abstractmethod
    async def status(self) -> dict:
        """Backend status for /api/sync + settings UI."""

    # -- team-scoped Drive folders --------------------------------------------
    # Each team connects its own Google account at creation; folder lookups and
    # sharing always run through THAT team's credentials, never the host's.

    async def set_team_root(self, team_id: str, folder_id: str) -> None:
        """Pin a team's Drive folder so its paths resolve inside it."""

    async def team_folder_info(self, team_id: str, folder_id: str) -> dict:
        """Return {'id', 'name', 'url'} for a Drive folder, verified through
        the team's own connected account.

        Raises DriveError (NotFoundError) when the folder does not exist or is
        not accessible with the team's account.
        """
        raise DriveError("Folder lookup is not supported by this storage backend")

    async def team_share_folder(self, team_id: str, folder_id: str, email: str, role: str = "writer") -> None:
        """Grant a member access to the team's folder via the team's account."""

    async def team_unshare_folder(self, team_id: str, folder_id: str, email: str) -> None:
        """Revoke a member's access to the team's folder via the team's account."""

    async def team_status(self, team_id: str) -> dict:
        """Connection status of one team: {connected, account}."""

    # -- per-team OAuth client + token management (server-side secrets) -------

    async def set_team_client(self, team_id: str, client_id: str, client_secret: str, redirect_uri: str) -> None:
        """Store a team's own Google OAuth client credentials server-side."""
        raise DriveError("Per-team OAuth clients are not supported by this storage backend")

    def team_client(self, team_id: str) -> dict | None:
        """Load the stored OAuth client for a team, or None."""

    def team_token_exists(self, team_id: str) -> bool:
        return False

    async def save_team_token(self, team_id: str, payload: dict) -> None:
        """Persist the OAuth token obtained from the team's callback."""

    async def delete_team_token(self, team_id: str) -> bool:
        return False

    async def team_authorize_url(self, team_id: str, state: str) -> str:
        """Google consent URL built from the team's stored client."""
        raise DriveError("Per-team OAuth clients are not supported by this storage backend")

    async def exchange_team_code(self, team_id: str, code: str, redirect_uri: str) -> dict:
        """Exchange an OAuth code for a token using the team's client credentials."""
        raise DriveError("Per-team OAuth clients are not supported by this storage backend")

    async def share_folder(self, folder_id: str, email: str, role: str = "writer") -> None:
        """Grant a Google account permission on a folder (best effort)."""

    async def unshare_folder(self, folder_id: str, email: str) -> None:
        """Revoke a Google account's permission on a folder (best effort)."""
