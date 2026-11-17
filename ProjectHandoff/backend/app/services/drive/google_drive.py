from __future__ import annotations

"""
Multi-tenant Google Drive backend.

Each team connects its OWN Google account at team creation:

    Create team (name + their OAuth client id/secret)
      -> one Google consent for the owner's account
      -> token stored server-side under .tokens/teams/{team_id}/
      -> team pastes its Drive folder link; every path below resolves inside it
      -> members never see Google anything (they just log in)

Session routing:

- Team-scoped paths (TeamData/{tid}/…, Projects/{tid}/…, Events/{tid}/…,
  Backups/{tid}/…) run through the TEAM's own session (its account, its
  folder, its quotas) when the team has connected.
- Teams that have not connected yet (or legacy deployments) fall back to the
  HOST session (the single organizer token at PH_GOOGLE_TOKEN_FILE) when one
  exists — preserving the pre-multi-tenant deployment layout byte-for-byte.
- Without any token, team paths are staged on the server's local disk
  (LocalDriveBackend) until the team links its folder; linking migrates the
  staged data into the team's Drive folder.
- Global tables (users/teams/credentials/invitations/activity + global
  backups) live in the HOST session when present, else on server disk — the
  account registry is server-side in a public deployment.
"""

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
from .local import LocalDriveBackend

FOLDER_MIME = "application/vnd.google-apps.folder"
# Full Drive scope (not drive.file): teams bring their *own* folders by pasting
# a link, and the backend manages sharing permissions on their behalf —
# drive.file would only ever see files this app created itself.
SCOPES = ["https://www.googleapis.com/auth/drive"]

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_EXCHANGE_URL = "https://oauth2.googleapis.com/token"

# Socket timeout for one Drive HTTP call (never hang the shared I/O queue).
DRIVE_HTTP_TIMEOUT = 30


def _q_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class _GoogleSession:
    """One Google account's working set: credentials, service, Drive lock.

    Sessions are per account (host + one per connected team) so teams never
    block each other and never share credentials.
    """

    def __init__(self, token_path: Path, timeout_seconds: int, client_id: str = "", client_secret: str = "", root_folder_id: str = "", root_folder_name: str = "ProjectHandoff") -> None:
        self.token_path = token_path
        self.timeout_seconds = timeout_seconds
        self.fallback_client_id = client_id
        self.fallback_client_secret = client_secret
        self.root_folder_id = root_folder_id
        self.root_folder_name = root_folder_name
        self._io_lock = asyncio.Lock()
        self._creds: Any = None
        self._service: Any = None
        self._token_mtime: float = -1.0
        self._folder_cache: dict[str, str] = {}
        self._root_anchor_id: str = ""

    # -- credentials ---------------------------------------------------------

    def token_file_exists(self) -> bool:
        return self.token_path.is_file()

    def token_recently_written(self, seconds: float = 120) -> bool:
        try:
            return time.time() - self.token_path.stat().st_mtime < seconds
        except OSError:
            return False

    def save_oauth_token(self, payload: dict) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), "utf-8")
        os.replace(tmp, self.token_path)
        self._creds = None
        self._service = None
        self._token_mtime = -1.0

    def delete_oauth_token(self) -> bool:
        if self.token_path.exists():
            self.token_path.unlink()
            self._creds = None
            self._service = None
            self._token_mtime = -1.0
            return True
        return False

    def _load_creds(self) -> Any:
        if not self.token_path.exists():
            raise DriveAuthError(
                "Google Drive is not authorized for this account. "
                "The team owner must connect Drive from the team page before the app can use it."
            )
        mtime = self.token_path.stat().st_mtime
        if self._creds is None or mtime != self._token_mtime:
            from google.oauth2.credentials import Credentials

            data = json.loads(self.token_path.read_text("utf-8"))
            self._creds = Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", TOKEN_EXCHANGE_URL),
                client_id=data.get("client_id") or self.fallback_client_id or None,
                client_secret=data.get("client_secret") or self.fallback_client_secret or None,
                scopes=data.get("scopes") or SCOPES,
            )
            self._service = None
            self._token_mtime = mtime
        return self._creds

    def _persist_creds(self) -> None:
        c = self._creds
        data = {
            "token": c.token,
            "refresh_token": c.refresh_token,
            "token_uri": c.token_uri,
            "client_id": c.client_id,
            "client_secret": c.client_secret,
            "scopes": list(c.scopes or SCOPES),
        }
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, self.token_path)
        self._token_mtime = self.token_path.stat().st_mtime

    # -- call plumbing ---------------------------------------------------------

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
                    "The team owner must reconnect Drive from the team page."
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
                inner.timeout = self.timeout_seconds
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
                        "Check the account's permissions on the team folder or reconnect Drive."
                    ) from exc2
            if status == 404:
                raise NotFoundError("Google Drive resource not found") from exc
            if 500 <= status < 600:
                raise DriveTransientError(f"Google Drive transient error (HTTP {status})") from exc
            raise DriveError(f"Google Drive error (HTTP {status})") from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise DriveTransientError(f"Network error talking to Google Drive: {exc}") from exc

    async def call(self, fn: Callable[[Any], Any]) -> Any:
        async with self._io_lock:
            return await asyncio.to_thread(self._sync_call, fn)

    # -- drive operations (one account's namespace) ----------------------------

    async def read_file(self, path: str, anchor: str = "", mapped_path: str | None = None) -> tuple[str, str]:
        use_path = mapped_path if mapped_path is not None else path

        def op(svc: Any) -> tuple[str, str]:
            meta = self._find_file_sync(svc, use_path, anchor)
            if meta is None:
                raise NotFoundError(f"File not found: {path}")
            data = svc.files().get_media(fileId=meta["id"]).execute()
            return data.decode("utf-8"), str(meta.get("headRevisionId") or "")

        return await self.call(op)

    async def write_file(self, path: str, content: str, expected_revision: str | None = None, anchor: str = "", mapped_path: str | None = None) -> str:
        from googleapiclient.http import MediaInMemoryUpload

        data = content.encode("utf-8")
        use_path = mapped_path if mapped_path is not None else path

        def op(svc: Any) -> str:
            name = use_path.rpartition("/")[2]
            if "/" in use_path:
                parent = self._ensure_folder_sync(svc, use_path.rpartition("/")[0], anchor)
            else:
                parent = anchor or self._root_anchor_sync(svc)
            meta = self._find_file_sync(svc, use_path, anchor)
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

        return await self.call(op)

    async def upload_file(self, folder_path: str, filename: str, data: bytes, mimetype: str = "application/octet-stream", anchor: str = "", mapped_folder: str | None = None) -> str:
        from googleapiclient.http import MediaInMemoryUpload

        use_folder = mapped_folder if mapped_folder is not None else folder_path

        def op(svc: Any) -> str:
            parent = self._ensure_folder_sync(svc, use_folder, anchor)
            media = MediaInMemoryUpload(data, mimetype=mimetype)
            created = (
                svc.files()
                .create(body={"name": filename, "parents": [parent]}, media_body=media, fields="id")
                .execute()
            )
            return created["id"]

        return await self.call(op)

    async def download_file(self, file_id: str) -> bytes:
        return await self.call(lambda svc: svc.files().get_media(fileId=file_id).execute())

    async def delete_file(self, file_id: str) -> None:
        await self.call(lambda svc: svc.files().delete(fileId=file_id).execute())

    async def list_folder(self, folder_path: str, anchor: str = "", mapped_folder: str | None = None) -> list[dict]:
        use_folder = mapped_folder if mapped_folder is not None else folder_path

        def op(svc: Any) -> list[dict]:
            folder = self._ensure_folder_sync(svc, use_folder, anchor)
            resp = (
                svc.files()
                .list(q=f"'{folder}' in parents and trashed=false", fields="files(id, name)", pageSize=100)
                .execute()
            )
            return resp.get("files", [])

        return await self.call(op)

    async def status(self) -> dict:
        def op(svc: Any) -> dict:
            about = svc.about().get(fields="user").execute()
            return {"connected": True, "account": about.get("user", {}).get("emailAddress")}

        try:
            return await self.call(op)
        except (DriveAuthError, DriveError):
            return {"connected": False, "account": None}

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

        return await self.call(op)

    async def share_folder(self, folder_id: str, email: str, role: str = "writer") -> None:
        def op(svc: Any) -> None:
            svc.permissions().create(
                fileId=folder_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=False,
            ).execute()

        await self.call(op)

    async def unshare_folder(self, folder_id: str, email: str) -> None:
        def op(svc: Any) -> None:
            resp = svc.permissions().list(fileId=folder_id, fields="permissions(id, emailAddress)").execute()
            for perm in resp.get("permissions", []):
                if (perm.get("emailAddress") or "").lower() == email.lower():
                    svc.permissions().delete(fileId=folder_id, permissionId=perm["id"]).execute()

        await self.call(op)

    # -- raw sync helpers (used inside call() closures) -------------------------

    def _root_anchor_sync(self, svc: Any) -> str:
        """Resolve (or create) the account's ProjectHandoff root folder.

        Unanchored paths (global registry tables, or a connected team that
        hasn't linked a folder yet) live inside it — matching the legacy
        single-organizer layout.
        """
        if self._root_anchor_id:
            return self._root_anchor_id
        if self.root_folder_id:
            self._root_anchor_id = self.root_folder_id
            return self._root_anchor_id
        name = self.root_folder_name
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
        self._root_anchor_id = fid
        return fid

    def _ensure_folder_sync(self, svc: Any, path: str, anchor: str = "") -> str:
        if not anchor:
            anchor = self._root_anchor_sync(svc)
        parts = [p for p in path.split("/") if p]
        parent = anchor
        acc: list[str] = []
        for part in parts:
            acc.append(part)
            key = f"{anchor}|{'/'.join(acc)}" if anchor else "/".join(acc)
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

    def _find_file_sync(self, svc: Any, path: str, anchor: str = "") -> dict | None:
        parent_path, _, name = path.rpartition("/")
        if parent_path:
            parent = self._ensure_folder_sync(svc, parent_path, anchor)
        else:
            parent = anchor or self._root_anchor_sync(svc)
        q = f"'{parent}' in parents and name='{_q_escape(name)}' and trashed=false"
        resp = svc.files().list(q=q, fields="files(id, headRevisionId)", pageSize=2).execute()
        files = resp.get("files", [])
        return files[0] if files else None

    def clear_folder_cache(self) -> None:
        self._folder_cache.clear()


class GoogleDriveBackend(DriveBackend):
    """Multi-tenant Google Drive backend.

    One HOST session (optional, legacy single-organizer deployments and the
    global registry) plus one session per connected team. Path-based routing
    picks the right session for every operation.
    """

    mode = "drive"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Host session — the optional single-organizer account.
        self._host = _GoogleSession(
            Path(settings.google_token_file), settings.drive_timeout_seconds,
            settings.google_client_id, settings.google_client_secret,
            settings.drive_root_folder_id, settings.drive_root_folder_name,
        )
        # Server-side staging area for teams that haven't connected yet
        # (and for the global registry when there is no host session).
        self._local = LocalDriveBackend(settings.local_data_dir)
        # team_id -> connected session
        self._team_sessions: dict[str, _GoogleSession] = {}
        # team_id -> Drive folder id (the folder the team pasted at setup)
        self._team_roots: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Session resolution                                                  #
    # ------------------------------------------------------------------ #

    def _team_token_dir(self, team_id: str) -> Path:
        return Path(self.settings.google_token_file).parent / "teams" / team_id

    def _session_for_team(self, team_id: str) -> _GoogleSession:
        if team_id in self._team_sessions:
            return self._team_sessions[team_id]
        session = _GoogleSession(
            self._team_token_dir(team_id) / "token.json",
            self.settings.drive_timeout_seconds,
        )
        self._team_sessions[team_id] = session
        return session

    def _route(self, path: str) -> tuple[_GoogleSession | None, LocalDriveBackend | None, str, str]:
        """Resolve a virtual path to ``(google_session, local_backend, anchor, mapped_path)``.

        Exactly one of google_session / local_backend is used.
        """
        parts = [p for p in path.split("/") if p]
        team_id = ""
        if len(parts) >= 2:
            first, second = parts[0], parts[1]
            if first == "TeamData" and not second.endswith(".csv") and second != "global":
                team_id = second
            elif first in ("Projects", "Events", "Backups") and second != "global":
                team_id = second

        if not team_id:
            # Global registry: host session when a host token exists, else disk.
            if self._host.token_file_exists():
                return self._host, None, "", path
            return None, self._local, "", path

        anchor = self._team_roots.get(team_id, "")
        mapped = self._map_team_path(path, team_id, anchor) if anchor else path

        if self._session_for_team(team_id).token_file_exists():
            return self._session_for_team(team_id), None, anchor, mapped
        if self._host.token_file_exists():
            # Legacy deployment: unconnected teams keep working through the
            # host account exactly as before multi-tenancy existed.
            return self._host, None, anchor, mapped
        # Not connected yet: stage on the server's disk until the team links
        # its folder (data is migrated into Drive at link time).
        return None, self._local, "", path

    def _map_team_path(self, path: str, team_id: str, anchor: str) -> str:
        """Map a team-scoped virtual path inside the team's folder:

            TeamData/{tid}/tasks.csv        -> <anchor>/AppData/tasks.csv
            TeamData/{tid}/files/…          -> <anchor>/Files/…
            Projects/{tid}/{pid}/files/…    -> <anchor>/Projects/{pid}/files/…
            Events/{tid}/{eid}/files/…      -> <anchor>/Events/{eid}/files/…
            Backups/{tid}/{table}/…         -> <anchor>/Backups/{table}/…
        """
        parts = [p for p in path.split("/") if p]
        rest = parts[2:]
        if parts[0] == "TeamData":
            # team-level uploads live in Files/, tables in AppData/
            return anchor + "/" + ("/".join(["Files"] + rest[1:] if rest and rest[0] == "files" else ["AppData"] + rest))
        if parts[0] == "Backups":
            return anchor + "/" + "/".join(["Backups"] + rest)
        return anchor + "/" + "/".join([parts[0]] + rest)  # Projects / Events — drop the team_id level

    # ------------------------------------------------------------------ #
    # DriveBackend interface                                              #
    # ------------------------------------------------------------------ #

    async def ensure_root(self) -> None:
        await self._local.ensure_root()
        if self._host.token_file_exists():
            # Make sure the host account's ProjectHandoff root folder exists.
            await self._host.call(lambda svc: self._host._root_anchor_sync(svc))
        await self._reload_team_roots()

    async def ensure_folder(self, path: str) -> str:
        session, local, anchor, mapped = self._route(path)
        if local is not None:
            return await local.ensure_folder(path)
        return await session.call(lambda svc: session._ensure_folder_sync(svc, mapped, anchor))

    async def file_exists(self, path: str) -> bool:
        session, local, anchor, mapped = self._route(path)
        if local is not None:
            return await local.file_exists(path)
        return await session.call(lambda svc: session._find_file_sync(svc, mapped, anchor) is not None)

    async def read_file(self, path: str) -> tuple[str, str]:
        session, local, anchor, mapped = self._route(path)
        if local is not None:
            return await local.read_file(path)
        return await session.read_file(path, anchor=anchor, mapped_path=mapped)

    async def write_file(self, path: str, content: str, expected_revision: str | None = None) -> str:
        session, local, anchor, mapped = self._route(path)
        if local is not None:
            return await local.write_file(path, content, expected_revision)
        return await session.write_file(path, content, expected_revision, anchor=anchor, mapped_path=mapped)

    async def upload_file(self, folder_path: str, filename: str, data: bytes, mimetype: str = "application/octet-stream") -> str:
        session, local, anchor, mapped = self._route(folder_path)
        if local is not None:
            return await local.upload_file(folder_path, filename, data, mimetype)
        return await session.upload_file(folder_path, filename, data, mimetype, anchor=anchor, mapped_folder=mapped)

    async def download_file(self, file_id: str, team_id: str = "") -> bytes:
        if team_id and self._session_for_team(team_id).token_file_exists():
            return await self._session_for_team(team_id).download_file(file_id)
        return await self._host.download_file(file_id)

    async def delete_file(self, file_id: str, team_id: str = "") -> None:
        if team_id and self._session_for_team(team_id).token_file_exists():
            await self._session_for_team(team_id).delete_file(file_id)
        else:
            await self._host.delete_file(file_id)

    async def list_folder(self, path: str) -> list[dict]:
        session, local, anchor, mapped = self._route(path)
        if local is not None:
            return await local.list_folder(path)
        return await session.list_folder(path, anchor=anchor, mapped_folder=mapped)

    async def status(self) -> dict:
        if not self._host.token_file_exists():
            return {"mode": "drive", "connected": False, "account": None}
        st = await self._host.status()
        return {"mode": "drive", **st}

    # ------------------------------------------------------------------ #
    # Team-scoped Drive folders                                           #
    # ------------------------------------------------------------------ #

    async def set_team_root(self, team_id: str, folder_id: str) -> None:
        """Pin (or clear, with "") a team's Drive folder."""
        if folder_id:
            self._team_roots[team_id] = folder_id
        else:
            self._team_roots.pop(team_id, None)
        for session in (self._session_for_team(team_id), self._host):
            session.clear_folder_cache()

    async def team_folder_info(self, team_id: str, folder_id: str) -> dict:
        return await self._session_for_team(team_id).folder_info(folder_id)

    async def team_share_folder(self, team_id: str, folder_id: str, email: str, role: str = "writer") -> None:
        await self._session_for_team(team_id).share_folder(folder_id, email, role)

    async def team_unshare_folder(self, team_id: str, folder_id: str, email: str) -> None:
        await self._session_for_team(team_id).unshare_folder(folder_id, email)

    async def team_status(self, team_id: str) -> dict:
        session = self._session_for_team(team_id)
        if not session.token_file_exists():
            return {"connected": False, "account": None}
        return await session.status()

    async def _reload_team_roots(self) -> None:
        """Load team_id -> folder id from the global teams table (server-side)."""
        try:
            content, _ = await self.read_file("TeamData/teams.csv")
        except NotFoundError:
            return
        except DriveError:
            return
        reader = csv.reader(io.StringIO(content, newline=""))
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
        self._team_roots = roots

    # ------------------------------------------------------------------ #
    # Per-team OAuth client + token management                            #
    # ------------------------------------------------------------------ #

    async def set_team_client(self, team_id: str, client_id: str, client_secret: str, redirect_uri: str) -> None:
        path = self._team_token_dir(team_id) / "oauth_client.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}),
            "utf-8",
        )
        os.replace(tmp, path)

    def team_client(self, team_id: str) -> dict | None:
        path = self._team_token_dir(team_id) / "oauth_client.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.get("client_id") and data.get("client_secret"):
                return data
        except (ValueError, OSError):
            pass
        return None

    def team_token_exists(self, team_id: str) -> bool:
        return self._session_for_team(team_id).token_file_exists()

    async def save_team_token(self, team_id: str, payload: dict) -> None:
        await asyncio.to_thread(self._session_for_team(team_id).save_oauth_token, payload)

    async def delete_team_token(self, team_id: str) -> bool:
        return await asyncio.to_thread(self._session_for_team(team_id).delete_oauth_token)

    async def team_authorize_url(self, team_id: str, state: str) -> str:
        client = self.team_client(team_id)
        if client is None:
            raise DriveAuthError("This team has not configured its Google OAuth client yet")
        from urllib.parse import urlencode

        params = urlencode({
            "client_id": client["client_id"],
            "redirect_uri": client.get("redirect_uri") or self.settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        })
        return f"{OAUTH_AUTH_URL}?{params}"

    async def exchange_team_code(self, team_id: str, code: str, redirect_uri: str) -> dict:
        client = self.team_client(team_id)
        if client is None:
            raise DriveAuthError("This team has not configured its Google OAuth client yet")

        import httpx

        response = await httpx.AsyncClient().post(
            TOKEN_EXCHANGE_URL,
            data={
                "code": code,
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if response.status_code != 200:
            raise DriveAuthError(f"Google rejected the authorization code (HTTP {response.status_code})")
        token_data = response.json()
        return {
            "token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "token_uri": token_data.get("token_uri", TOKEN_EXCHANGE_URL),
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "scopes": (token_data.get("scope") or " ".join(SCOPES)).split() or SCOPES,
        }

    # Legacy host-session helpers (kept for the Settings-page flow) ---------

    def token_file_exists(self) -> bool:
        return self._host.token_file_exists()

    def save_oauth_token(self, payload: dict) -> None:
        self._host.save_oauth_token(payload)

    def delete_oauth_token(self) -> bool:
        return self._host.delete_oauth_token()
