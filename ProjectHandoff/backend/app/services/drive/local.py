from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from .base import (
    DriveBackend,
    DriveError,
    NotFoundError,
    StaleRevision,
)

_INDEX = "_index.json"


class LocalDriveBackend(DriveBackend):
    """Explicit development backend: mirrors the Drive API semantics with
    plain files under a local directory.

    This is NOT a persistent production database and is only selected when the
    operator explicitly sets PH_STORAGE_MODE=local with PH_ALLOW_LOCAL_STORAGE=true.
    It intentionally implements the same interface (including revisions) so the
    whole application is exercised identically to production.
    """

    mode = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._io_lock = asyncio.Lock()
        self._index_path = self.root / _INDEX
        self._index: dict[str, str] = {}
        self._load_index()

    # -- helpers ------------------------------------------------------------
    def _resolve(self, path: str) -> Path:
        if ".." in Path(path).parts or path.startswith("/"):
            raise DriveError(f"Invalid storage path: {path!r}")
        resolved = (self.root / path).resolve()
        if not str(resolved).startswith(str(self.root)):
            raise DriveError(f"Path escapes storage root: {path!r}")
        return resolved

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text("utf-8"))
            except (ValueError, OSError):
                self._index = {}

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=0), "utf-8")

    def _revision(self, path: Path) -> str:
        st = path.stat()
        return f"{st.st_mtime_ns}-{st.st_size}"

    # -- API -----------------------------------------------------------------
    async def ensure_root(self) -> None:
        async with self._io_lock:
            for folder in ("TeamData", "Projects", "Events", "Backups"):
                (self.root / folder).mkdir(parents=True, exist_ok=True)
            if not self._index_path.exists():
                self._save_index()

    async def ensure_folder(self, path: str) -> str:
        async with self._io_lock:
            self._resolve(path).mkdir(parents=True, exist_ok=True)
            return path

    async def file_exists(self, path: str) -> bool:
        return self._resolve(path).is_file()

    async def read_file(self, path: str) -> tuple[str, str]:
        target = self._resolve(path)
        if not target.is_file():
            raise NotFoundError(f"File not found: {path}")
        return target.read_text("utf-8"), self._revision(target)

    async def write_file(self, path: str, content: str, expected_revision: str | None = None) -> str:
        async with self._io_lock:
            target = self._resolve(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and expected_revision not in (None, ""):
                current = self._revision(target)
                if current != expected_revision:
                    raise StaleRevision(
                        f"{path} changed externally (rev {current} != expected {expected_revision})"
                    )
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(content, "utf-8")
            os.replace(tmp, target)
            return self._revision(target)

    async def upload_file(self, folder_path: str, filename: str, data: bytes, mimetype: str = "application/octet-stream") -> str:
        async with self._io_lock:
            folder = self._resolve(folder_path)
            folder.mkdir(parents=True, exist_ok=True)
            file_id = "loc-" + uuid.uuid4().hex
            target = folder / filename
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            self._load_index()
            self._index[file_id] = str(target.relative_to(self.root))
            self._save_index()
            return file_id

    async def download_file(self, file_id: str, team_id: str = "") -> bytes:
        async with self._io_lock:
            self._load_index()
            rel = self._index.get(file_id)
            if rel is None:
                raise NotFoundError(f"Unknown file id: {file_id}")
            target = self.root / rel
            if not target.is_file():
                raise NotFoundError(f"File missing on disk: {file_id}")
            return target.read_bytes()

    async def delete_file(self, file_id: str, team_id: str = "") -> None:
        async with self._io_lock:
            self._load_index()
            rel = self._index.get(file_id)
            if rel is None:
                raise NotFoundError(f"Unknown file id: {file_id}")
            target = self.root / rel
            if target.exists():
                target.unlink()
            self._index.pop(file_id, None)
            self._save_index()

    async def list_folder(self, path: str) -> list[dict]:
        target = self._resolve(path)
        if not target.is_dir():
            return []
        self._load_index()
        entries = []
        for child in sorted(target.iterdir()):
            if not child.is_file() or child.name == _INDEX:
                continue
            file_id = "loc-" + uuid.uuid4().hex
            self._index[file_id] = str(child.relative_to(self.root))
            entries.append({"id": file_id, "name": child.name})
        self._save_index()
        return entries

    async def status(self) -> dict:
        return {"mode": "local", "authorized": True, "account": None}
