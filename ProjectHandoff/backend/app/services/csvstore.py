from __future__ import annotations

import asyncio
import csv
import io
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.services.drive.base import (
    DriveAuthError,
    DriveError,
    DriveTransientError,
    NotFoundError,
    StaleRevision,
)

# ---------------------------------------------------------------------------
# Schemas (canonical column order for every CSV file)
# ---------------------------------------------------------------------------

SCHEMAS: dict[str, list[str]] = {
    "users": ["user_id", "name", "email", "role", "team_id", "joined_at", "status"],
    "teams": [
        "team_id", "name", "description", "owner_id", "created_at", "status",
        "drive_folder_id", "drive_folder_url",
    ],
    "credentials": ["user_id", "password_hash", "created_at"],
    "projects": [
        "project_id", "name", "description", "owner_id", "start_date",
        "deadline", "status", "priority", "created_at", "updated_at",
    ],
    "events": [
        "event_id", "name", "description", "start_date", "end_date",
        "owner_id", "status", "created_at",
    ],
    "departments": ["department_id", "event_id", "name", "coordinator_id", "description", "status"],
    "department_members": ["department_id", "user_id", "added_by", "added_at"],
    "tasks": [
        "task_id", "project_id", "event_id", "department_id", "title", "description",
        "assigned_to", "created_by", "priority", "status", "deadline", "version",
        "created_at", "updated_at",
    ],
    "handovers": [
        "handover_id", "task_id", "previous_owner_id", "proposed_owner_id",
        "completed_work", "remaining_work", "current_state", "blockers",
        "next_actions", "relevant_files", "deadline", "status", "created_at", "accepted_at",
    ],
    "comments": ["comment_id", "task_id", "user_id", "comment", "created_at"],
    "activity": [
        "activity_id", "team_id", "project_id", "task_id", "user_id",
        "action", "description", "timestamp",
    ],
    "invitations": ["invitation_id", "team_id", "email", "role", "token_hash", "expires_at", "status"],
    "attachments": [
        "attachment_id", "task_id", "project_id", "drive_file_id", "file_name",
        "uploaded_by", "uploaded_at",
    ],
}

# Tables with a team_id column live in the shared TeamData folder;
# everything else is a per-team CSV under TeamData/{team_id}/.
GLOBAL_TABLES = frozenset({"users", "teams", "credentials", "invitations", "activity"})
TEAM_TABLES = frozenset(set(SCHEMAS) - GLOBAL_TABLES)

# Primary key column per table; "" means composite key (no unique single id).
ID_COLUMNS: dict[str, str] = {
    "users": "user_id",
    "teams": "team_id",
    "credentials": "user_id",
    "projects": "project_id",
    "events": "event_id",
    "departments": "department_id",
    "department_members": "",
    "tasks": "task_id",
    "handovers": "handover_id",
    "comments": "comment_id",
    "activity": "activity_id",
    "invitations": "invitation_id",
    "attachments": "attachment_id",
}

ACTIVITY_ROW_LIMIT = 5000


class StoreError(Exception):
    """Base storage-layer error."""


class ValidationError(StoreError):
    """Row/CSV content failed validation."""


class ConflictError(StoreError):
    """Uniqueness or version conflict."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def serialize_rows(table: str, rows: list[dict]) -> str:
    """Serialize rows to RFC-4180 CSV with the canonical header.

    csv.writer handles all quoting/escaping (commas, quotes, newlines).
    """
    header = SCHEMAS[table]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([str(row.get(col, "") or "") for col in header])
    return buf.getvalue()


def parse_csv(table: str, content: str) -> list[dict]:
    """Parse CSV content into dicts, validating the header against the schema."""
    reader = csv.reader(io.StringIO(content, newline=""))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return []
    expected = SCHEMAS[table]
    if header != expected:
        # Tolerate CSVs written before columns were appended to the schema
        # (e.g. teams.csv without drive_folder_*): old files are a strict
        # prefix of the current header and missing cells read as "".
        if not (len(header) < len(expected) and expected[: len(header)] == header):
            raise ValidationError(
                f"{table}.csv header mismatch: expected {expected}, found {header}"
            )
    rows: list[dict] = []
    for line_no, raw in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw):
            continue  # skip blank lines
        if len(raw) > len(expected):
            raise ValidationError(f"{table}.csv line {line_no}: too many columns ({len(raw)})")
        cells = [cell.strip() for cell in raw]
        # pad rows from older schema versions so every row is schema-complete
        rows.append({col: (cells[i] if i < len(cells) else "") for i, col in enumerate(expected)})
    return rows


def _validate_ids(table: str, rows: list[dict]) -> None:
    id_col = ID_COLUMNS[table]
    if not id_col:
        return  # composite-key table (department_members)
    seen: set[str] = set()
    for row in rows:
        value = row.get(id_col, "")
        if not value:
            raise ValidationError(f"{table}.csv row missing {id_col}")
        if value in seen:
            raise ConflictError(f"{table}.csv duplicate {id_col}: {value}")
        seen.add(value)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class CsvStore:
    """CSV persistence engine on top of a DriveBackend.

    Guarantees and design notes:

    - One authoritative backend instance; writes to the same CSV are serialized
      with an asyncio lock per (team, table), so two writes never interleave.
    - Every mutation re-reads the latest content from Drive before applying the
      change, then writes with the revision it observed. If the file changed
      underneath (external edit), StaleRevision triggers a re-read/re-apply
      retry loop (optimistic concurrency). Drive revisions are *detection*, not
      an atomic compare-and-swap primitive.
    - Successful reads are cached briefly (READ_CACHE_TTL). The auth check,
      list pages and the background sync poll stop costing a Drive round-trip
      every time, so navigating the app feels instant. Our own writes refresh
      the cache; StaleRevision busts it — external edits are still detected on
      the next write attempt.
    - Transient read failures are retried a couple of times before surfacing;
      the frontend additionally retries syncs, so a blip self-heals.
    - Before each successful overwrite the previous content is pushed to
      Backups/<scope>/<table>/ with a timestamp (best effort).
    - Recoverable failures (transient network/5xx, stale revisions) are retried;
      unrecoverable failures leave the previous content intact and raise.
    - If a CSV becomes unreadable (corrupt/renamed), read() attempts recovery
      from the newest parseable backup before failing.
    """

    MAX_RETRIES = 4
    READ_CACHE_TTL = 8.0  # seconds a successful read stays valid in memory
    READ_RETRIES = 2  # extra attempts for transient failures on read

    def __init__(self, backend: Any, backup_retention: int = 20, read_cache_ttl: float | None = None) -> None:
        self.backend = backend
        self.backup_retention = backup_retention
        self.read_cache_ttl = self.READ_CACHE_TTL if read_cache_ttl is None else read_cache_ttl
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._read_cache: dict[tuple[str, str], tuple[float, list[dict], str]] = {}

    # -- read cache ------------------------------------------------------------
    def _cache_get(self, key: tuple[str, str]) -> tuple[list[dict], str] | None:
        hit = self._read_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < self.read_cache_ttl:
            return hit[1], hit[2]
        return None

    def _cache_put(self, key: tuple[str, str], rows: list[dict], revision: str) -> None:
        self._read_cache[key] = (time.monotonic(), rows, revision)

    # -- paths ---------------------------------------------------------------
    def table_path(self, table: str, team_id: str = "") -> str:
        if table not in SCHEMAS:
            raise StoreError(f"Unknown table: {table}")
        if table in GLOBAL_TABLES:
            return f"TeamData/{table}.csv"
        if not team_id:
            raise StoreError(f"Table {table!r} is team-scoped; team_id required")
        return f"TeamData/{team_id}/{table}.csv"

    async def _lock_for(self, team_id: str, table: str) -> asyncio.Lock:
        key = (team_id, table)
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = asyncio.Lock()
            return lock

    # -- initialization -------------------------------------------------------
    async def init(self) -> None:
        await self.backend.ensure_root()
        for table in sorted(GLOBAL_TABLES):
            path = self.table_path(table)
            if not await self.backend.file_exists(path):
                await self.backend.write_file(path, serialize_rows(table, []))
        for table in sorted(TEAM_TABLES):
            await self.backend.ensure_folder(f"Backups/global/{table}")

    async def ensure_team(self, team_id: str) -> None:
        for table in sorted(TEAM_TABLES):
            path = self.table_path(table, team_id)
            if not await self.backend.file_exists(path):
                async with await self._lock_for(team_id, table):
                    if not await self.backend.file_exists(path):
                        await self.backend.write_file(path, serialize_rows(table, []))
            await self.backend.ensure_folder(f"Backups/{team_id}/{table}")

    # -- reads ----------------------------------------------------------------
    async def read(self, table: str, team_id: str = "", fresh: bool = False) -> tuple[list[dict], str]:
        """Read a table; served from a short-TTL cache unless ``fresh``.

        Transient backend failures are retried before surfacing to the caller.
        """
        key = (team_id, table)
        if not fresh:
            cached = self._cache_get(key)
            if cached is not None:
                return cached

        path = self.table_path(table, team_id)
        content = revision = None
        last_error: Exception | None = None
        for attempt in range(self.READ_RETRIES + 1):
            try:
                content, revision = await self.backend.read_file(path)
                break
            except NotFoundError:
                # Self-heal: recreate a missing CSV (e.g. deleted externally).
                content, revision = serialize_rows(table, []), ""
                try:
                    revision = await self.backend.write_file(path, content, expected_revision=None)
                except DriveError:
                    pass
                self._cache_put(key, [], revision)
                return [], revision
            except DriveTransientError as exc:
                last_error = exc
                await asyncio.sleep(0.3 * (attempt + 1))
        if content is None:
            raise StoreError(f"Failed to read {path} after {self.READ_RETRIES + 1} attempts: {last_error}")

        try:
            rows = parse_csv(table, content)
        except ValidationError:
            recovered = await self._recover_from_backup(table, team_id)
            if recovered is not None:
                rows, backup_revision = recovered
                try:  # repair the main file with the recovered content
                    await self.backend.write_file(path, serialize_rows(table, rows), expected_revision=None)
                except DriveError:
                    pass
                self._cache_put(key, rows, backup_revision)
                return rows, backup_revision
            raise

        self._cache_put(key, rows, revision)
        return rows, revision

    async def _recover_from_backup(self, table: str, team_id: str) -> tuple[list[dict], str] | None:
        scope = team_id or "global"
        try:
            entries = await self.backend.list_folder(f"Backups/{scope}/{table}")
        except DriveError:
            return None
        for entry in sorted(entries, key=lambda e: e["name"], reverse=True):
            try:
                data = await self.backend.download_file(entry["id"])
                rows = parse_csv(table, data.decode("utf-8"))
                _validate_ids(table, rows)
                return rows, f"backup:{entry['name']}"
            except (DriveError, ValidationError, ConflictError, UnicodeDecodeError):
                continue
        return None

    # -- mutation --------------------------------------------------------------
    async def mutate(
        self,
        table: str,
        fn: Callable[[list[dict]], list[dict]],
        team_id: str = "",
    ) -> list[dict]:
        """Serialized read-modify-write.

        ``fn(rows)`` receives the freshest rows and must return the new rows
        (or raise). The lock guarantees only one writer per CSV at a time.
        """
        lock = await self._lock_for(team_id, table)
        key = (team_id, table)
        async with lock:
            path = self.table_path(table, team_id)
            last_error: Exception | None = None
            for attempt in range(self.MAX_RETRIES):
                rows, revision = await self.read(table, team_id, fresh=True)
                new_rows = fn(list(rows))  # business errors propagate untouched
                _validate_ids(table, new_rows)
                content = serialize_rows(table, new_rows)
                try:
                    new_revision = await self.backend.write_file(
                        path, content, expected_revision=revision or None
                    )
                except StaleRevision as exc:
                    last_error = exc
                    self._read_cache.pop(key, None)  # external edit — refetch on retry
                    continue
                except DriveTransientError as exc:
                    last_error = exc
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                except DriveAuthError:
                    raise  # not recoverable without user action
                except DriveError as exc:
                    last_error = exc
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                # Success — snapshot the written content as a recovery point
                # and refresh the read cache with what is now stored.
                await self._backup(table, team_id, content)
                self._cache_put(key, new_rows, new_revision)
                return new_rows
            raise StoreError(
                f"Failed to write {table}.csv after {self.MAX_RETRIES} attempts: {last_error}"
            )

    async def _backup(self, table: str, team_id: str, current_content: str) -> None:
        scope = team_id or "global"
        folder = f"Backups/{scope}/{table}"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        try:
            await self.backend.upload_file(folder, f"{stamp}-{table}.csv", current_content.encode("utf-8"), "text/csv")
            if self.backup_retention > 0:
                entries = await self.backend.list_folder(folder)
                by_name = sorted((e for e in entries if not e["name"].startswith("_")), key=lambda e: e["name"])
                for entry in by_name[: max(0, len(by_name) - self.backup_retention)]:
                    try:
                        await self.backend.delete_file(entry["id"])
                    except DriveError:
                        pass
        except DriveError:
            pass  # backups are best effort; the main write already succeeded

    # -- convenience -------------------------------------------------------------
    async def query(self, table: str, team_id: str = "") -> list[dict]:
        rows, _rev = await self.read(table, team_id)
        return rows

    async def insert(self, table: str, row: dict, team_id: str = "") -> dict:
        row = dict(row)
        id_col = ID_COLUMNS[table]
        if id_col:
            row.setdefault(id_col, new_id())

        def fn(rows: list[dict]) -> list[dict]:
            rows.append(row)
            return rows

        await self.mutate(table, fn, team_id)
        return row

    async def update(self, table: str, row_id: str, patch: dict, team_id: str = "") -> dict:
        id_col = ID_COLUMNS[table]

        def fn(rows: list[dict]) -> list[dict]:
            for row in rows:
                if row.get(id_col) == row_id:
                    row.update(patch)
                    return rows
            raise NotFoundError(f"{table} {row_id} not found")

        await self.mutate(table, fn, team_id)
        return dict(patch)

    def require(self, rows: list[dict], table: str, row_id: str) -> dict:
        id_col = ID_COLUMNS[table]
        for row in rows:
            if row.get(id_col) == row_id:
                return row
        raise NotFoundError(f"{table} {row_id} not found")
