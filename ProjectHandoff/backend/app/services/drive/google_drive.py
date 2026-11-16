from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from app.config import Settings
from app.services.drive_link import drive_folder_url

from .base import (
    DriveAuthError,
    DriveBackend,
    DriveError,
    DriveTransientError,
    NotFoundError,
    StaleRevision,
)

FOLDER_MIME = "application/vnd.google-apps.folder"
# Full Drive scope (not drive.file): teams bring their *own* folders by pasting
# a link, and the backend manages sharing permissions on the organizer's
# behalf — drive.file would only ever see files this app created itself.
SCOPES = ["https://www.googleapis.com/auth/drive"]

# How often the backend re-reads TeamData/teams.csv to pick up team folders.
TEAM_ROOTS_TTL_SECONDS = 15.0
# Socket timeout for one Drive HTTP call (never hang the shared I/O queue).
DRIVE_HTTP_TIMEOUT = 30


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
        # team_id -> Drive folder id (the folder the team pasted at setup)
        self._team_roots: dict[str, str] = {}
        self._team_roots_at: float = -1e9

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
            # cache_discovery=True: keep Google's (large) API description on
            # disk instead of re-downloading it on every service rebuild.
            service = build("drive", "v3", credentials=creds, cache_discovery=True)
            # googleapiclient sets no socket timeout by default — a stalled
            # connection would hold the shared I/O lock (and every pending
            # request) forever. Bound every call explicitly.
            wrapped = getattr(service, "_http", None)
            inner = getattr(wrapped, "http", None)
            if inner is not None:
                inner.timeout = self.settings.drive_timeout_seconds
            self._service = service
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

    def _load_team_roots_sync(self, svc: Any) -> None:
        """Refresh team_id -> drive folder id from TeamData/teams.csv."""
        self._team_roots_at = time.monotonic()
        try:
            meta = self._find_file_sync(svc, "TeamData/teams.csv")
            if meta is None:
                return
            data = svc.files().get_media(fileId=meta["id"]).execute()
            text = data.decode("utf-8")
        except (DriveError, UnicodeDecodeError):
            return
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            return
        if "team_id" not in header or "drive_folder_id" not in header:
            return
        id_at, folder_at = header.index("team_id"), header.index("drive_folder_id")
        roots = {
            row[id_at].strip(): row[folder_at].strip()
            for row in reader
            if len(row) > max(id_at, folder_at) and row[id_at].strip() and row[folder_at].strip()
        }
        if roots != self._team_roots:
            self._team_roots = roots
            self._folder_cache.clear()  # team paths may now resolve elsewhere

    def _map_path_sync(self, svc: Any, path: str) -> tuple[str, str]:
        """Resolve a virtual path to ``(anchor_folder_id, mapped_subpath)``.

        Returns ("", path) unchanged when the path belongs to the global root
        (global tables, teams without a Drive folder). Team-scoped paths are
        remapped inside the folder the team pasted at setup:

            TeamData/{tid}/tasks.csv        -> <team folder>/AppData/tasks.csv
            TeamData/{tid}/files/…          -> <team folder>/Files/…
            Projects/{tid}/{pid}/files/…    -> <team folder>/Projects/{pid}/files/…
            Events/{tid}/{eid}/files/…      -> <team folder>/Events/{eid}/files/…
            Backups/{tid}/{table}/…         -> <team folder>/Backups/{table}/…
        """
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("TeamData", "Projects", "Events", "Backups"):
            second = parts[1]
            is_team_scope = second != "global" and (
                parts[0] != "TeamData" or not second.endswith(".csv")
            )
            if is_team_scope:
                if time.monotonic() - self._team_roots_at > TEAM_ROOTS_TTL_SECONDS:
                    self._load_team_roots_sync(svc)
                anchor = self._team_roots.get(second)
                if anchor:
                    rest = parts[2:]
                    if parts[0] == "TeamData":
                        # team-level uploads live in Files/, tables in AppData/
                        mapped = ["Files"] + rest[1:] if rest and rest[0] == "files" else ["AppData"] + rest
                    elif parts[0] == "Backups":
                        mapped = ["Backups"] + rest
                    else:  # Projects / Events — drop the team_id level
                        mapped = [parts[0]] + rest
                    return anchor, "/".join(mapped)
        return "", path

    def _ensure_folder_sync(self, svc: Any, path: str) -> str:
        anchor, mapped_path = self._map_path_sync(svc, path)
        mapped_parts = [p for p in mapped_path.split("/") if p]
        parent = anchor or self._root_folder_sync(svc)
        acc: list[str] = []
        for mapped_part in mapped_parts:
            acc.append(mapped_part)
            # Cache keys stay in mapped-path space; team-scoped keys are
            # qualified by the anchor folder id so they can never collide
            # with global paths (e.g. team AppData vs global TeamData).
            key = f"{anchor}|{'/'.join(acc)}" if anchor else "/".join(acc)
            if key in self._folder_cache:
                parent = self._folder_cache[key]
                continue
            q = (
                f"'{parent}' in parents and name='{_q_escape(mapped_part)}' "
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
                        body={"name": mapped_part, "mimeType": FOLDER_MIME, "parents": [parent]},
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

    # ------------------------------------------------------------------ #
    # Team-scoped Drive folders                                           #
    # ------------------------------------------------------------------ #

    async def set_team_root(self, team_id: str, folder_id: str) -> None:
        """Pin (or clear, with "") a team's Drive folder; cache is refreshed."""
        if folder_id:
            self._team_roots[team_id] = folder_id
        else:
            self._team_roots.pop(team_id, None)
        self._team_roots_at = time.monotonic()
        self._folder_cache.clear()

    async def folder_info(self, folder_id: str) -> dict:
        def op(svc: Any) -> dict:
            meta = svc.files().get(fileId=folder_id, fields="id,name,mimeType,webViewLink").execute()
            if meta.get("mimeType") != FOLDER_MIME:
                raise DriveError("That Drive link points to a file, not a folder")
            return {
                "id": meta["id"],
                "name": meta.get("name", ""),
                "url": meta.get("webViewLink") or drive_folder_url(folder_id),
            }

        return await self._call(op)

    async def share_folder(self, folder_id: str, email: str, role: str = "writer") -> None:
        def op(svc: Any) -> None:
            svc.permissions().create(
                fileId=folder_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=False,
            ).execute()

        await self._call(op)

    async def unshare_folder(self, folder_id: str, email: str) -> None:
        def op(svc: Any) -> None:
            resp = svc.permissions().list(fileId=folder_id, fields="permissions(id, emailAddress)").execute()
            for perm in resp.get("permissions", []):
                if (perm.get("emailAddress") or "").lower() == email.lower():
                    svc.permissions().delete(fileId=folder_id, permissionId=perm["id"]).execute()

        await self._call(op)
