from __future__ import annotations

from app.services.csvstore import CsvStore, TeamArchivedError, now_iso

TABLE = "team_memberships"


def _state(value: str | None) -> str:
    return value or "active"


async def memberships_for_user(db: CsvStore, user_id: str) -> list[dict]:
    return [row for row in await db.query(TABLE) if row.get("user_id") == user_id]


async def active_memberships(db: CsvStore, user_id: str) -> list[dict]:
    return [
        row for row in await memberships_for_user(db, user_id)
        if row.get("state") == "active"
    ]


async def membership_for(db: CsvStore, user_id: str, team_id: str) -> dict | None:
    return next(
        (
            row for row in await db.query(TABLE)
            if row.get("user_id") == user_id and row.get("team_id") == team_id
        ),
        None,
    )


async def has_membership(db: CsvStore, user_id: str, team_id: str) -> bool:
    row = await membership_for(db, user_id, team_id)
    return bool(row and row.get("state") != "removed")


async def add_team_membership(
    db: CsvStore,
    *,
    user_id: str,
    team_id: str,
    email: str,
    role: str,
    state: str = "active",
    is_current: bool = False,
) -> dict:
    existing = await membership_for(db, user_id, team_id)
    if existing is not None:
        return existing
    return await db.insert(
        TABLE,
        {
            "user_id": user_id,
            "team_id": team_id,
            "email": email,
            "role": role,
            "state": _state(state),
            "is_current": "1" if is_current else "0",
            "joined_at": now_iso(),
        },
    )


async def set_current_membership(db: CsvStore, user_id: str, team_id: str) -> None:
    def update(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user_id:
                row["is_current"] = "1" if row.get("team_id") == team_id else "0"
        return rows

    await db.mutate(TABLE, update)
    memberships = await memberships_for_user(db, user_id)
    row = next((m for m in memberships if m.get("team_id") == team_id), None)
    if row is None:
        raise TeamArchivedError("No membership for that team")


async def mark_team_observed(db: CsvStore, team_id: str) -> int:
    count = 0

    def update(rows: list[dict]) -> list[dict]:
        nonlocal count
        for row in rows:
            if row.get("team_id") == team_id and row.get("state") == "active":
                row["state"] = "observer"
                count += 1
        return rows

    await db.mutate(TABLE, update)
    return count


async def set_membership_state(db: CsvStore, user_id: str, team_id: str, state: str) -> None:
    def update(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user_id and row.get("team_id") == team_id:
                row["state"] = state
                if state == "removed":
                    row["is_current"] = "0"
        return rows

    await db.mutate(TABLE, update)


async def set_membership_role(db: CsvStore, user_id: str, team_id: str, role: str) -> None:
    def update(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("user_id") == user_id and row.get("team_id") == team_id:
                row["role"] = role
        return rows

    await db.mutate(TABLE, update)


async def remove_team_membership(db: CsvStore, user_id: str, team_id: str) -> None:
    def remove(rows: list[dict]) -> list[dict]:
        return [
            row for row in rows
            if not (row.get("user_id") == user_id and row.get("team_id") == team_id)
        ]

    await db.mutate(TABLE, remove)
