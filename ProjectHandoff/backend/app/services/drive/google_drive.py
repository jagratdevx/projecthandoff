from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable

from app.config import Settings

from .base import (
    DriveAuthError,
    DriveBackend,
    DriveError,
    DriveTransientError,
    NotFoundError,
    StaleRevision,
)

FOLDER_MIME = "application/vnd.google-apps.folder"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _q_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveBackend(DriveBackend):
    """Google Drive v3 backend using the organizer's OAuth credentials.

    - Access tokens are refreshed automatically; the refreshed token set is
      persisted back to the token file.
    - All Drive HTTP calls are serialized through one asyncio lock: the
      googleapiclient service object is not safe for concurrent use and the
      serialized-writes requirement relies on this anyway.
    - OAuth refresh tokens/secrets never leave the backend process.
    """

    mode = "drive"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._io_lock = asyncio.Lock()
        self._folder_cache: dict[str, str] = {}
        self._creds: Any = None
        self._service: Any = None
        self._token_mtime: float = -1.0

    # ------------------------------------------------------------------ #
    # Credentials                                                         #
    # ------------------------------------------------------------------ #

    @property
    def _token_path(self) -> Path:
        return Path(self.settings.google_token_file)

    def token_file_exists(self) -> bool:
        return self._token_path.is_file()

    def save_oauth_token(self, payload: dict) -> None:
        """Persist OAuth credentials obtained from the callback (or tests)."""
        path = self._token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), "utf-8")
        os.replace(tmp, path)
        self._creds = None
        self._service = None
        self._token_mtime = -1.0

    def delete_oauth_token(self) -> bool:
        path = self._token_path
        if path.exists():
            path.unlink()
            self._creds = None
            self._service = None
            self._token_mtime = -1.0
            return True
        return False

    def _load_creds(self) -> Any:
        path = self._token_path
        if not path.exists():
            raise DriveAuthError(
                "Google Drive is not authorized. The organizer must connect the "
                "backend via the Settings page (OAuth) before the app can use Drive."
            )
        mtime = path.stat().st_mtime
        if self._creds is None or mtime != self._token_mtime:
            from google.oauth2.credentials import Credentials

            data = json.loads(path.read_text("utf-8"))
            self._creds = Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id") or self.settings.google_client_id or None,
                client_secret=data.get("client_secret") or self.settings.google_client_secret or None,
                scopes=data.get("scopes") or SCOPES,
            )
            self._service = None
            self._token_mtime = mtime
        return self._creds

    def _persist_creds(self) -> None:
        path = self._token_path
        c = self._creds
        data = {
            "token": c.token,
            "refresh_token": c.refresh_token,
            "token_uri": c.token_uri,
            "client_id": c.client_id,
            "client_secret": c.client_secret,
            "scopes": list(c.scopes or SCOPES),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, path)
        self._token_mtime = path.stat().st_mtime

    # ------------------------------------------------------------------ #
    # Call plumbing                                                       #
    # ------------------------------------------------------------------ #

    def _sync_call(self, fn: Callable[[Any], Any]) -> Any:
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        creds = self._load_creds()
        if creds.expired or not creds.valid:
            try:
                creds.refresh(Request())
            except Exception as exc:  # RefreshError and network failures
                raise DriveAuthError(
                    f"Google OAuth token refresh failed: {exc}. "
                    "The organizer must re-authorize the backend from the Settings page."
                ) from exc
            self._persist_creds()
        if self._service is None:
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        try:
            return fn(self._service)
        except HttpError as exc:
            status = getattr(exc.resp, "status", 0)
            if status in (401, 403):
                try:
                    creds.refresh(Request())
                    self._persist_creds()
                    return fn(self._service)
                except Exception as exc2:
                    raise DriveAuthError(
                        f"Google Drive rejected the request even after a token refresh ({status}). "
                        "Check the organizer's permissions or re-authorize."
                    ) from exc2
            if status == 404:
                raise NotFoundError("Google Drive resource not found") from exc
            if 500 <= status < 600:
                raise DriveTransientError(f"Google Drive transient error (HTTP {status})") from exc
            raise DriveError(f"Google Drive error (HTTP {status})") from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise DriveTransientError(f"Network error talking to Google Drive: {exc}") from exc

    async def _call(self, fn: Callable[[Any], Any]) -> Any:
        async with self._io_lock:
            return await asyncio.to_thread(self._sync_call, fn)

    # ------------------------------------------------------------------ #
    # Folder hierarchy                                                    #
    # ------------------------------------------------------------------ #

    def _root_folder_sync(self, svc: Any) -> str:
        if "" in self._folder_cache:
            return self._folder_cache[""]
        if self.settings.drive_root_folder_id:
            self._folder_cache[""] = self.settings.drive_root_folder_id
            return self._folder_cache[""]
        name = self.settings.drive_root_folder_name
        escaped = _q_escape(name)
        resp = (
            svc.files()
            .list(
                q=f"'root' in parents and name='{escaped}' and mimeType='{FOLDER_MIME}' and trashed=false",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
        )
        files = resp.get("files", [])
        if files:
            fid = files[0]["id"]
        else:
            fid = (
                svc.files()
                .create(body={"name": name, "mimeType": FOLDER_MIME}, fields="id")
                .execute()["id"]
            )
        self._folder_cache[""] = fid
        return fid

    def _ensure_folder_sync(self, svc: Any, path: str) -> str:
        parts = [p for p in path.split("/") if p]
        parent = self._root_folder_sync(svc)
        acc: list[str] = []
        for part in parts:
            acc.append(part)
            key = "/".join(acc)
            if key in self._folder_cache:
                parent = self._folder_cache[key]
                continue
            q = (
                f"'{parent}' in parents and name='{_q_escape(part)}' "
                f"and mimeType='{FOLDER_MIME}' and trashed=false"
            )
            resp = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
            files = resp.get("files", [])
            if files:
                fid = files[0]["id"]
            else:
                fid = (
                    svc.files()
                    .create(
                        body={"name": part, "mimeType": FOLDER_MIME, "parents": [parent]},
                        fields="id",
                    )
                    .execute()["id"]
                )
            self._folder_cache[key] = fid
            parent = fid
        return parent

    def _find_file_sync(self, svc: Any, path: str) -> dict | None:
        parent_path, _, name = path.rpartition("/")
        parent = self._ensure_folder_sync(svc, parent_path) if parent_path else self._root_folder_sync(svc)
        q = f"'{parent}' in parents and name='{_q_escape(name)}' and trashed=false"
        resp = svc.files().list(q=q, fields="files(id, headRevisionId)", pageSize=2).execute()
        files = resp.get("files", [])
        return files[0] if files else None

    # ------------------------------------------------------------------ #
    # DriveBackend interface                                              #
    # ------------------------------------------------------------------ #

    async def ensure_root(self) -> None:
        await self._call(lambda svc: self._root_folder_sync(svc))

    async def ensure_folder(self, path: str) -> str:
        return await self._call(lambda svc: self._ensure_folder_sync(svc, path))

    async def file_exists(self, path: str) -> bool:
        return await self._call(lambda svc: self._find_file_sync(svc, path) is not None)

    async def read_file(self, path: str) -> tuple[str, str]:
        def op(svc: Any) -> tuple[str, str]:
            meta = self._find_file_sync(svc, path)
            if meta is None:
                raise NotFoundError(f"File not found: {path}")
            data = svc.files().get_media(fileId=meta["id"]).execute()
            return data.decode("utf-8"), str(meta.get("headRevisionId") or "")

        return await self._call(op)

    async def write_file(self, path: str, content: str, expected_revision: str | None = None) -> str:
        from googleapiclient.http import MediaInMemoryUpload

        data = content.encode("utf-8")

        def op(svc: Any) -> str:
            parent_path, _, name = path.rpartition("/")
            parent = self._ensure_folder_sync(svc, parent_path) if parent_path else self._root_folder_sync(svc)
            meta = self._find_file_sync(svc, path)
            media = MediaInMemoryUpload(data, mimetype="text/csv")
            if meta is not None:
                head = str(meta.get("headRevisionId") or "")
                if expected_revision not in (None, "") and head and head != expected_revision:
                    raise StaleRevision(
                        f"{path} changed on Drive since it was read "
                        f"(remote rev {head}, expected {expected_revision})"
                    )
                svc.files().update(fileId=meta["id"], media_body=media).execute()
                head2 = (
                    svc.files().get(fileId=meta["id"], fields="headRevisionId").execute().get("headRevisionId")
                )
                return str(head2 or "")
            created = (
                svc.files()
                .create(
                    body={"name": name, "parents": [parent]},
                    media_body=media,
                    fields="id, headRevisionId",
                )
                .execute()
            )
            return str(created.get("headRevisionId") or created["id"])

        return await self._call(op)

    async def upload_file(self, folder_path: str, filename: str, data: bytes, mimetype: str = "application/octet-stream") -> str:
        from googleapiclient.http import MediaInMemoryUpload

        def op(svc: Any) -> str:
            parent = self._ensure_folder_sync(svc, folder_path)
            media = MediaInMemoryUpload(data, mimetype=mimetype)
            created = (
                svc.files()
                .create(body={"name": filename, "parents": [parent]}, media_body=media, fields="id")
                .execute()
            )
            return created["id"]

        return await self._call(op)

    async def download_file(self, file_id: str) -> bytes:
        return await self._call(lambda svc: svc.files().get_media(fileId=file_id).execute())

    async def delete_file(self, file_id: str) -> None:
        await self._call(lambda svc: svc.files().delete(fileId=file_id).execute())

    async def list_folder(self, path: str) -> list[dict]:
        def op(svc: Any) -> list[dict]:
            folder = self._ensure_folder_sync(svc, path)
            resp = (
                svc.files()
                .list(q=f"'{folder}' in parents and trashed=false", fields="files(id, name)", pageSize=100)
                .execute()
            )
            return resp.get("files", [])

        return await self._call(op)

    async def status(self) -> dict:
        def op(svc: Any) -> dict:
            about = svc.about().get(fields="user").execute()
            return {"mode": "drive", "authorized": True, "account": about.get("user", {}).get("emailAddress")}

        try:
            return await self._call(op)
        except (DriveAuthError, DriveError):
            return {"mode": "drive", "authorized": False, "account": None}
