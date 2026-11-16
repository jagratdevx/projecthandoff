from __future__ import annotations

"""Short-TTL read cache: repeated reads (auth, pages, sync polls) must not
cost a Drive round-trip; our own writes refresh the cache."""

import asyncio

from app.services.csvstore import CsvStore, now_iso
from app.services.drive.local import LocalDriveBackend


class CountingBackend(LocalDriveBackend):
    """Counts read_file calls so tests can see whether the cache was used."""

    def __init__(self, root, ttl_store: dict | None = None):
        super().__init__(root)
        self.read_calls = 0

    async def read_file(self, path):
        self.read_calls += 1
        return await super().read_file(path)


def run(coro):
    return asyncio.run(coro)


def _user(i: str) -> dict:
    return {"user_id": i, "name": "A", "email": f"{i}@x.dev", "role": "member",
            "team_id": "", "joined_at": now_iso(), "status": "active"}


def test_repeated_reads_are_cached(tmp_path):
    backend = CountingBackend(tmp_path / "data")
    store = CsvStore(backend, read_cache_ttl=5)
    run(store.init())

    run(store.read("users"))
    run(store.read("users"))
    run(store.read("users"))
    assert backend.read_calls == 1  # second and third reads served from memory

    # fresh=True always hits the backend
    run(store.read("users", fresh=True))
    assert backend.read_calls == 2


def test_write_refreshes_cache(tmp_path):
    backend = CountingBackend(tmp_path / "data")
    store = CsvStore(backend, read_cache_ttl=5)
    run(store.init())
    run(store.read("users"))

    run(store.insert("users", _user("u1")))
    calls_after_insert = backend.read_calls  # the mutation itself re-read fresh (by design)

    rows = run(store.query("users"))  # the query afterwards must be a cache hit AND include the insert
    assert backend.read_calls == calls_after_insert
    assert [r["user_id"] for r in rows] == ["u1"]


def test_cache_expires_after_ttl(tmp_path):
    backend = CountingBackend(tmp_path / "data")
    store = CsvStore(backend, read_cache_ttl=0.05)
    run(store.init())

    run(store.read("users"))
    run(store.read("users"))
    assert backend.read_calls == 1

    import time
    time.sleep(0.08)  # let the TTL lapse
    run(store.read("users"))
    assert backend.read_calls == 2


def test_transient_read_failure_is_retried(tmp_path):
    class FlakyReadBackend(CountingBackend):
        def __init__(self, root, failures: int):
            super().__init__(root)
            self.failures = failures
            self.armed = False

        async def read_file(self, path):
            if self.armed and self.failures > 0:
                self.failures -= 1
                from app.services.drive.base import DriveTransientError
                raise DriveTransientError("simulated 500")
            return await super().read_file(path)

    backend = FlakyReadBackend(tmp_path / "data", failures=1)
    store = CsvStore(backend, read_cache_ttl=0)
    run(store.init())
    backend.armed = True

    rows = run(store.query("users"))  # first attempt fails, retry succeeds
    assert rows == []
    assert backend.failures == 0  # the retry consumed the transient failure
    assert backend.read_calls == 1  # one successful read got through
