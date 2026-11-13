from __future__ import annotations

import asyncio

import pytest

from app.services.csvstore import SCHEMAS, ConflictError, CsvStore, StoreError, now_iso
from app.services.drive.base import DriveAuthError, DriveTransientError, StaleRevision
from app.services.drive.local import LocalDriveBackend


def make_store(tmp_path, backend=None) -> CsvStore:
    return CsvStore(backend or LocalDriveBackend(tmp_path / "data"))


def test_init_creates_global_tables_with_headers(tmp_path):
    store = make_store(tmp_path)
    asyncio.run(store.init())
    for table in ("users", "teams", "credentials", "invitations", "activity"):
        content = (tmp_path / "data" / "TeamData" / f"{table}.csv").read_text()
        assert content.splitlines()[0] == ",".join(SCHEMAS[table])


def test_ensure_team_creates_team_tables(tmp_path):
    store = make_store(tmp_path)
    asyncio.run(store.init())
    asyncio.run(store.ensure_team("team1"))
    tasks_path = tmp_path / "data" / "TeamData" / "team1" / "tasks.csv"
    assert tasks_path.exists()
    assert tasks_path.read_text().splitlines()[0] == ",".join(SCHEMAS["tasks"])


def test_team_tables_require_team_id(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(StoreError):
        store.table_path("tasks")


def test_concurrent_inserts_are_all_persisted(tmp_path):
    """Serialized per-file writes: N concurrent mutations must all survive."""
    store = make_store(tmp_path)
    asyncio.run(store.init())

    async def scenario():
        async def insert(i: int):
            await store.insert(
                "users",
                {"user_id": f"u{i}", "name": f"User {i}", "email": f"u{i}@x.dev", "role": "member",
                 "team_id": "", "joined_at": now_iso(), "status": "active"},
            )

        await asyncio.gather(*(insert(i) for i in range(40)))

    asyncio.run(scenario())
    rows, _rev = asyncio.run(store.read("users"))
    assert len(rows) == 40
    assert {r["user_id"] for r in rows} == {f"u{i}" for i in range(40)}
    # file must still be valid CSV with exactly one header
    lines = (tmp_path / "data" / "TeamData" / "users.csv").read_text().splitlines()
    assert lines[0] == ",".join(SCHEMAS["users"])
    assert len(lines) == 41


class SneakyBackend(LocalDriveBackend):
    """Simulates an external writer touching the CSV between read and write."""

    def __init__(self, root, perturbation, target: str = "users.csv"):
        super().__init__(root)
        self.perturbation = perturbation
        self.target = target
        self.armed = True

    async def write_file(self, path, content, expected_revision=None):
        if self.armed and path.endswith(self.target) and self._resolve(path).exists():
            self.armed = False
            with self._resolve(path).open("a") as fh:  # external edit invisible to the store's revision
                fh.write(self.perturbation)
        return await super().write_file(path, content, expected_revision)


def test_stale_revision_triggers_reapply(tmp_path):
    backend = SneakyBackend(tmp_path / "data", "u-ext,External Editor,ext@x.dev,member,,2026-01-01T00:00:00+00:00,active\n")
    store = CsvStore(backend)
    asyncio.run(store.init())

    async def scenario():
        await store.insert("users", {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "member",
                                     "team_id": "", "joined_at": now_iso(), "status": "active"})

    asyncio.run(scenario())  # retry loop must merge the external row back in
    rows, _ = asyncio.run(store.read("users"))
    ids = {r["user_id"] for r in rows}
    assert "u1" in ids
    assert "u-ext" in ids  # external edit preserved, not silently overwritten


class AlwaysStaleBackend(LocalDriveBackend):
    async def write_file(self, path, content, expected_revision=None):
        if expected_revision is not None:
            raise StaleRevision("simulated permanent conflict")
        return await super().write_file(path, content, expected_revision)


def test_permanent_stale_conflict_leaves_data_intact(tmp_path):
    store = make_store(tmp_path, AlwaysStaleBackend(tmp_path / "data"))
    asyncio.run(store.init())
    before = (tmp_path / "data" / "TeamData" / "users.csv").read_text()

    async def scenario():
        with pytest.raises(StoreError):
            await store.insert("users", {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "member",
                                         "team_id": "", "joined_at": now_iso(), "status": "active"})

    asyncio.run(scenario())
    assert (tmp_path / "data" / "TeamData" / "users.csv").read_text() == before


class FlakyBackend(LocalDriveBackend):
    def __init__(self, root, failures: int):
        super().__init__(root)
        self.failures = failures
        self.armed = False

    async def write_file(self, path, content, expected_revision=None):
        if self.armed and self.failures > 0:
            self.failures -= 1
            raise DriveTransientError("simulated 500 from Drive")
        return await super().write_file(path, content, expected_revision)


def test_transient_failures_are_retried(tmp_path):
    backend = FlakyBackend(tmp_path / "data", failures=2)
    store = make_store(tmp_path, backend)
    asyncio.run(store.init())
    backend.armed = True

    async def scenario():
        await store.insert("users", {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "member",
                                     "team_id": "", "joined_at": now_iso(), "status": "active"})

    asyncio.run(scenario())
    rows, _ = asyncio.run(store.read("users"))
    assert len(rows) == 1


def test_auth_error_is_not_swallowed(tmp_path):
    class AuthFailBackend(LocalDriveBackend):
        def __init__(self, root):
            super().__init__(root)
            self.armed = False

        async def write_file(self, path, content, expected_revision=None):
            if self.armed:
                raise DriveAuthError("token expired beyond refresh")
            return await super().write_file(path, content, expected_revision)

    backend = AuthFailBackend(tmp_path / "data")
    store = make_store(tmp_path, backend)
    asyncio.run(store.init())
    backend.armed = True

    async def scenario():
        with pytest.raises(DriveAuthError):
            await store.insert("users", {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "member",
                                         "team_id": "", "joined_at": now_iso(), "status": "active"})

    asyncio.run(scenario())


def test_backup_created_on_write(tmp_path):
    backend = LocalDriveBackend(tmp_path / "data")
    store = CsvStore(backend)
    asyncio.run(store.init())

    async def scenario():
        await store.insert("users", {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "member",
                                     "team_id": "", "joined_at": now_iso(), "status": "active"})
        await store.update("users", "u1", {"name": "A2"})

    asyncio.run(scenario())
    entries = asyncio.run(backend.list_folder("Backups/global/users"))
    assert len(entries) >= 1


def test_corrupt_csv_is_recovered_from_backup(tmp_path):
    backend = LocalDriveBackend(tmp_path / "data")
    store = CsvStore(backend)
    asyncio.run(store.init())

    async def scenario():
        await store.insert("users", {"user_id": "u1", "name": "A", "email": "a@x.dev", "role": "member",
                                     "team_id": "", "joined_at": now_iso(), "status": "active"})
        await store.update("users", "u1", {"name": "A v2"})
        # simulate corruption of the live file
        (tmp_path / "data" / "TeamData" / "users.csv").write_text("garbage,header\n1,2\n")

    asyncio.run(scenario())
    rows, _ = asyncio.run(store.read("users"))
    assert [r["user_id"] for r in rows] == ["u1"]
    assert rows[0]["name"] == "A v2"


def test_update_missing_row_raises_not_found(tmp_path):
    from app.services.csvstore import NotFoundError

    store = make_store(tmp_path)
    asyncio.run(store.init())

    async def scenario():
        with pytest.raises(NotFoundError):
            await store.update("users", "missing", {"name": "X"})

    asyncio.run(scenario())
