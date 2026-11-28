from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
        "subteam_id", "requirements",
    ],
    "events": [
        "event_id", "name", "description", "start_date", "end_date",
        "owner_id", "status", "created_at",
    ],
    "departments": ["department_id", "event_id", "name", "coordinator_id", "description", "status"],
    "subteams": [
        "subteam_id", "team_id", "name", "description",
        "folder_id", "folder_url", "created_at",
    ],
    "subteam_members": ["subteam_id", "user_id", "role", "added_by", "added_at"],
    "department_members": ["department_id", "user_id", "added_by", "added_at"],
    "tasks": [
        "task_id", "project_id", "event_id", "department_id", "title", "description",
        "assigned_to", "created_by", "priority", "status", "deadline", "version",
        "created_at", "updated_at", "subteam_id",
    ],
    "handovers": [
        "handover_id", "task_id", "previous_owner_id", "proposed_owner_id",
        "completed_work", "remaining_work", "current_state", "blockers",
        "next_actions", "relevant_files", "deadline", "status", "created_at", "accepted_at",
        "subteam_id",
    ],
    "comments": ["comment_id", "task_id", "user_id", "comment", "created_at"],
    "activity": [
        "activity_id", "team_id", "project_id", "task_id", "user_id",
        "action", "description", "timestamp",
    ],
    "activity_log": [
        "activity_id", "team_id", "subteam_id", "project_id", "task_id", "user_id",
        "action", "description", "timestamp", "source",
    ],
    "team_memberships": [
        "membership_id", "user_id", "team_id", "email", "role",
        "state", "is_current", "joined_at",
    ],
    "subteam_activity": [
        "activity_id", "team_id", "subteam_id", "project_id", "task_id", "user_id",
        "action", "description", "timestamp",
    ],
    "invitations": [
        "invitation_id", "team_id", "email", "role", "token_hash", "expires_at", "status",
        "subteam_id", "subteam_role",
    ],
    "attachments": [
        "attachment_id", "task_id", "project_id", "drive_file_id", "file_name",
        "uploaded_by", "uploaded_at",
    ],
}

# Tables with a team_id column live in the shared TeamData folder;
# everything else is a per-team CSV under TeamData/{team_id}/.
GLOBAL_TABLES = frozenset({
    "users", "teams", "credentials", "invitations", "activity", "team_memberships",
})
TEAM_TABLES = frozenset(set(SCHEMAS) - GLOBAL_TABLES)

# Primary key column per table; "" means composite key (no unique single id).
ID_COLUMNS: dict[str, str] = {
    "users": "user_id",
    "teams": "team_id",
    "credentials": "user_id",
    "projects": "project_id",
    "events": "event_id",
    "departments": "department_id",
    "subteams": "subteam_id",
    "subteam_members": "",
    "department_members": "",
    "tasks": "task_id",
    "handovers": "handover_id",
    "comments": "comment_id",
    "activity": "activity_id",
    "activity_log": "activity_id",
    "team_memberships": "membership_id",
    "subteam_activity": "activity_id",
    "invitations": "invitation_id",
    "attachments": "attachment_id",
}

ACTIVITY_ROW_LIMIT = 5000


class StoreError(Exception):
    """Base storage-layer error."""


class ValidationError(StoreError):
    """Row/CSV content failed validation."""


class TeamArchivedError(StoreError):
    """A completed team is read-only."""


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
    READ_CACHE_TTL = 60.0  # seconds before a cached table is refreshed in the background
    READ_RETRIES = 1  # extra attempts for transient failures on read
    _log = logging.getLogger("projecthandoff")

    def __init__(
        self,
        backend: Any,
        backup_retention: int = 20,
        read_cache_ttl: float | None = None,
        persistent_cache_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.backend = backend
        self.backup_retention = backup_retention
        self.read_cache_ttl = self.READ_CACHE_TTL if read_cache_ttl is None else read_cache_ttl
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._read_cache: dict[tuple[str, str], tuple[float, list[dict], str]] = {}
        self._refreshing: dict[tuple[str, str], asyncio.Task] = {}
        self._refresh_running = False
        self._active_writes = 0
        self._persistent_cache_path = Path(persistent_cache_path) if persistent_cache_path else None
        self._load_persistent_cache()

    # -- read cache ------------------------------------------------------------
    #
    # Two-layer design:
    #   * memory: every successful read is cached; our own writes update it.
    #   * disk:   the same entries are persisted so a restart starts warm. The
    #             first paint is served from disk immediately, then the
    #             background warm-up refreshes Drive in the background.
    #
    # Stale-while-revalidate: once an entry passes READ_CACHE_TTL we return it
    # right away and refresh it in the background. A slow Drive (often 1–3 s
    # per CSV here) can therefore never block a page load or a sync poll.

    def _cache_get(self, key: tuple[str, str], *, allow_stale: bool = False) -> tuple[list[dict], str] | None:
        hit = self._read_cache.get(key)
        if hit is None:
            return None
        if time.monotonic() - hit[0] < self.read_cache_ttl:
            return hit[1], hit[2]
        if allow_stale:
            self._schedule_refresh(key)
            return hit[1], hit[2]
        return None

    def _cache_put(self, key: tuple[str, str], rows: list[dict], revision: str) -> None:
        self._read_cache[key] = (time.monotonic(), rows, revision)
        self._save_persistent_cache()

    def _schedule_refresh(self, key: tuple[str, str]) -> None:
        existing = self._refreshing.get(key)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._refresh(key))
        self._refreshing[key] = task

        def _done(t: asyncio.Task) -> None:
            if self._refreshing.get(key) is t:
                self._refreshing.pop(key, None)
            if not t.cancelled() and t.exception() is not None:
                # _refresh already logs; retrieving the exception prevents
                # asyncio's "never retrieved" warning.
                pass

        task.add_done_callback(_done)

    async def _refresh(self, key: tuple[str, str]) -> None:
        team_id, table = key
        # Never let a burst of background refreshes queue in front of a write.
        # One refresh at a time, and none while a mutation is in flight.
        if self._refresh_running or self._active_writes:
            return
        self._refresh_running = True
        try:
            if self._active_writes:
                return
            await self._read_backend(table, team_id)
        except Exception as exc:  # noqa: BLE001 — stale data is better than a blank screen
            self._log.warning(
                "Background refresh failed for %s%s (serving cached rows): %s",
                table, f" ({team_id})" if team_id else "", exc,
            )
        finally:
            self._refresh_running = False

    async def flush_refreshes(self) -> None:
        """Wait for in-flight background refreshes (used by tests and shutdown)."""
        tasks = [t for t in self._refreshing.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- persistent cache -------------------------------------------------------
    def _load_persistent_cache(self) -> None:
        if self._persistent_cache_path is None or not self._persistent_cache_path.is_file():
            return
        try:
            data = json.loads(self._persistent_cache_path.read_text("utf-8"))
            entries = data.get("entries", {})
            if not isinstance(entries, dict):
                return
            for raw_key, entry in entries.items():
                team_id, _, table = str(raw_key).partition("|")
                if table not in SCHEMAS or not isinstance(entry, dict):
                    continue
                rows = entry.get("rows")
                if not isinstance(rows, list):
                    continue
                try:
                    _validate_ids(table, rows)
                except (ValidationError, ConflictError):
                    continue
                # Preserve the snapshot's age so the first access serves it
                # instantly but immediately schedules a background refresh if
                # it is older than the TTL.
                saved_at = float(entry.get("saved_at") or 0)
                age = max(0.0, time.time() - saved_at) if saved_at else float("inf")
                self._read_cache[(team_id, table)] = (
                    time.monotonic() - age, rows, str(entry.get("revision", "")),
                )
            if self._read_cache:
                self._log.info("Loaded %s cached tables from disk", len(self._read_cache))
        except (OSError, ValueError, TypeError) as exc:
            self._log.warning("Ignoring unreadable read cache: %s", exc)

    def _save_persistent_cache(self) -> None:
        if self._persistent_cache_path is None:
            return
        try:
            now = time.time()
            entries: dict[str, dict] = {}
            for (team_id, table), (ts, rows, revision) in self._read_cache.items():
                entries[f"{team_id}|{table}"] = {
                    "revision": revision,
                    "rows": rows,
                    "saved_at": now - max(0.0, time.monotonic() - ts),
                }
            payload = json.dumps({"version": 1, "entries": entries}, separators=(",", ":"))
            path = self._persistent_cache_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(payload, "utf-8")
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            self._log.warning("Could not persist read cache: %s", exc)

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

    async def _team_archived(self, team_id: str) -> bool:
        if not team_id:
            return False
        rows = await self.query("teams")
        row = next((item for item in rows if item.get("team_id") == team_id), None)
        return bool(row and row.get("status") == "archived")

    async def is_archived(self, team_id: str) -> bool:
        return await self._team_archived(team_id)

    async def assert_writable(self, team_id: str) -> None:
        if await self._team_archived(team_id):
            raise TeamArchivedError("This team is completed and read-only")

    async def _backfill_memberships(self) -> None:
        users = await self.query("users")
        teams = {t.get("team_id", ""): t for t in await self.query("teams")}
        existing = await self.query("team_memberships")
        seen = {(row.get("user_id", ""), row.get("team_id", "")) for row in existing}
        for user in users:
            team_id = user.get("team_id", "")
            if not team_id or (user.get("user_id", ""), team_id) in seen:
                continue
            archived = teams.get(team_id, {}).get("status") == "archived"
            await self.insert(
                "team_memberships",
                {
                    "user_id": user.get("user_id", ""),
                    "team_id": team_id,
                    "email": user.get("email", ""),
                    "role": user.get("role", "member"),
                    "state": "observer" if archived else "active",
                    "is_current": "1",
                    "joined_at": user.get("joined_at", ""),
                },
            )

    async def _mirror_activity(self) -> None:
        for team in await self.query("teams"):
            team_id = team.get("team_id", "")
            if not team_id:
                continue
            mirrored = {row.get("activity_id", "") for row in await self.query("activity_log", team_id)}
            for entry in await self.query("activity"):
                if entry.get("team_id") != team_id or entry.get("activity_id", "") in mirrored:
                    continue
                await self.insert(
                    "activity_log",
                    {**entry, "subteam_id": "", "source": "main"},
                    team_id,
                    allow_archived=True,
                )
                mirrored.add(entry.get("activity_id", ""))
            for entry in await self.query("subteam_activity", team_id):
                if entry.get("activity_id", "") in mirrored:
                    continue
                await self.insert(
                    "activity_log",
                    {**entry, "source": "subteam"},
                    team_id,
                    allow_archived=True,
                )
                mirrored.add(entry.get("activity_id", ""))

    # -- initialization -------------------------------------------------------
    async def init(self) -> None:
        await self.backend.ensure_root()
        for table in sorted(GLOBAL_TABLES):
            # A warm disk cache proves the table exists (and reads self-heal a
            # file deleted externally), so skip a slow Drive stat per table on
            # every restart.
            if ("", table) in self._read_cache:
                continue
            path = self.table_path(table)
            if not await self.backend.file_exists(path):
                await self.backend.write_file(path, serialize_rows(table, []))
        if not self._read_cache:
            for table in sorted(TEAM_TABLES):
                await self.backend.ensure_folder(f"Backups/global/{table}")

    async def backfill_membership_data(self) -> None:
        """Idempotent migration from the legacy single-team user model."""
        await self._backfill_memberships()
        await self._mirror_activity()

    async def backfill_project_scope_data(self) -> None:
        """Infer missing project/subteam links from existing tasks (idempotent)."""
        for team in await self.query("teams"):
            team_id = team.get("team_id", "")
            if not team_id:
                continue
            projects = await self.query("projects", team_id)
            tasks = await self.query("tasks", team_id)
            subteam_ids = {
                row.get("subteam_id", "")
                for row in await self.query("subteams", team_id)
                if row.get("subteam_id", "")
            }
            inferred: dict[str, str] = {}
            for project in projects:
                project_id = project.get("project_id", "")
                if not project_id or project.get("subteam_id"):
                    continue
                candidates = {
                    task.get("subteam_id", "")
                    for task in tasks
                    if task.get("project_id") == project_id
                    and task.get("subteam_id", "") in subteam_ids
                }
                if len(candidates) == 1:
                    inferred[project_id] = next(iter(candidates))
            if not inferred:
                continue

            def assign_projects(rows: list[dict]) -> list[dict]:
                for row in rows:
                    if row.get("project_id", "") in inferred and not row.get("subteam_id"):
                        row["subteam_id"] = inferred[row["project_id"]]
                return rows

            await self.mutate("projects", assign_projects, team_id, allow_archived=True)

            def assign_tasks(rows: list[dict]) -> list[dict]:
                for row in rows:
                    if row.get("project_id", "") in inferred and not row.get("subteam_id"):
                        row["subteam_id"] = inferred[row["project_id"]]
                return rows

            await self.mutate("tasks", assign_tasks, team_id, allow_archived=True)

    async def ensure_team(self, team_id: str) -> None:
        if all((team_id, table) in self._read_cache for table in TEAM_TABLES):
            return
        for table in sorted(TEAM_TABLES):
            path = self.table_path(table, team_id)
            if not await self.backend.file_exists(path):
                async with await self._lock_for(team_id, table):
                    if not await self.backend.file_exists(path):
                        await self.backend.write_file(path, serialize_rows(table, []))
            await self.backend.ensure_folder(f"Backups/{team_id}/{table}")

    # -- warming ----------------------------------------------------------------
    async def warm_cache(self) -> int:
        """Prefetch every table into the read cache (background startup job).

        The first UI hit after a restart otherwise pays a serialized Drive
        round-trip per screen; warming makes it instant. Best effort: failures
        per table are logged and skipped, never raised — the app still works,
        it just falls back to on-demand reads.

        When a disk snapshot was loaded, skip the bulk warm: every page is
        already instant, and each table refreshes on demand in the background
        as the user visits it. This avoids a multi-minute Drive storm at boot.
        """
        if self._read_cache:
            self._log.info(
                "Read cache loaded from disk (%s tables) — refreshing on demand",
                len(self._read_cache),
            )
            return len(self._read_cache)

        warmed = 0

        async def warm(table: str, team_id: str) -> None:
            nonlocal warmed
            try:
                await self.read(table, team_id, fresh=True)
                warmed += 1
            except Exception as exc:  # noqa: BLE001 — warming must never break startup
                logging.getLogger("projecthandoff").warning(
                    "Cache warm-up skipped %s%s: %s", table, f" ({team_id})" if team_id else "", exc
                )

        try:
            for row in await self.query("teams"):
                if row.get("status", "active") != "active":
                    continue
                team_id = row.get("team_id", "")
                if team_id:
                    await self.ensure_team(team_id)
                    for table in sorted(TEAM_TABLES):
                        await warm(table, team_id)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("projecthandoff").warning("Cache warm-up (teams) skipped: %s", exc)
        for table in sorted(GLOBAL_TABLES):
            await warm(table, "")
        return warmed

    # -- reads ----------------------------------------------------------------
    async def read(self, table: str, team_id: str = "", fresh: bool = False) -> tuple[list[dict], str]:
        """Read a table, serving cached rows instantly whenever possible.

        ``fresh=True`` (mutations and the startup warm-up) waits for Drive.
        Normal page loads and polls use stale-while-revalidate: stale rows are
        returned immediately while a single background refresh updates them.
        """
        key = (team_id, table)
        if not fresh:
            cached = self._cache_get(key, allow_stale=True)
            if cached is not None:
                return cached
            try:
                return await self._read_backend(table, team_id)
            except (StoreError, DriveError) as exc:
                # Cold cache + Drive trouble: if we have any snapshot at all,
                # keep the app usable instead of blanking the screen.
                hit = self._read_cache.get(key)
                if hit is not None:
                    self._log.warning(
                        "Read failed for %s%s; serving cached rows: %s",
                        table, f" ({team_id})" if team_id else "", exc,
                    )
                    return hit[1], hit[2]
                raise

        return await self._read_backend(table, team_id)

    async def _read_backend(self, table: str, team_id: str) -> tuple[list[dict], str]:
        key = (team_id, table)
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
        *,
        allow_archived: bool = False,
    ) -> list[dict]:
        """Serialized read-modify-write.

        ``fn(rows)`` receives the freshest rows and must return the new rows
        (or raise). The lock guarantees only one writer per CSV at a time.
        """
        if team_id and not allow_archived:
            await self.assert_writable(team_id)
        lock = await self._lock_for(team_id, table)
        key = (team_id, table)
        self._active_writes += 1
        try:
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
        finally:
            self._active_writes -= 1

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

    async def insert(self, table: str, row: dict, team_id: str = "", *, allow_archived: bool = False) -> dict:
        row = dict(row)
        id_col = ID_COLUMNS[table]
        if id_col:
            row.setdefault(id_col, new_id())

        def fn(rows: list[dict]) -> list[dict]:
            rows.append(row)
            return rows

        await self.mutate(table, fn, team_id, allow_archived=allow_archived)
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
