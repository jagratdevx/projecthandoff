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
    async def download_file(self, file_id: str) -> bytes: ...

    @abstractmethod
    async def delete_file(self, file_id: str) -> None: ...

    @abstractmethod
    async def list_folder(self, path: str) -> list[dict]:
        """Return [{'id': ..., 'name': ...}, ...] for immediate children."""

    @abstractmethod
    async def status(self) -> dict:
        """Backend status for /api/sync + settings UI."""
