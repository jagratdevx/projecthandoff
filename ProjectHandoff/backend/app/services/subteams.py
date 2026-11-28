from __future__ import annotations

from typing import Any

from app.services.csvstore import CsvStore, now_iso

FULL_ACCESS_ROLES = frozenset({"owner", "admin", "council", "teacher"})
SUBTEAM_ROLES = frozenset({"coordinator", "volunteer"})


def has_full_access(user: dict) -> bool:
    """Owners, admins, council and teachers can act on every subteam."""
    return user.get("role", "") in FULL_ACCESS_ROLES


async def get_subteam(db: CsvStore, team_id: str, subteam_id: str) -> dict | None:
    for row in await db.query("subteams", team_id):
        if row.get("subteam_id") == subteam_id:
            return row
    return None


async def memberships_for(db: CsvStore, team_id: str, user_id: str) -> dict[str, str]:
    rows = await db.query("subteam_members", team_id)
    return {
        row["subteam_id"]: row.get("role", "volunteer")
        for row in rows
        if row.get("user_id") == user_id and row.get("subteam_id")
    }


async def coordinator_of(db: CsvStore, team_id: str, user_id: str) -> set[str]:
    return {
        subteam_id
        for subteam_id, role in (await memberships_for(db, team_id, user_id)).items()
        if role == "coordinator"
    }


async def role_in_subteam(db: CsvStore, team_id: str, subteam_id: str, user_id: str) -> str:
    rows = await db.query("subteam_members", team_id)
    for row in rows:
        if row.get("subteam_id") == subteam_id and row.get("user_id") == user_id:
            return row.get("role", "")
    return ""


async def can_manage_subteam(db: CsvStore, user: dict, team_id: str, subteam_id: str) -> bool:
    if has_full_access(user):
        return True
    return await role_in_subteam(db, team_id, subteam_id, user["user_id"]) == "coordinator"


def can_view_all(user: dict) -> bool:
    """Overseers and global coordinators can read every subteam's projects."""
    return has_full_access(user) or user.get("role", "") == "coordinator"


async def membership_ids(db: CsvStore, team_id: str, user_id: str) -> set[str]:
    return set((await memberships_for(db, team_id, user_id)).keys())


async def visible_subteam_ids(db: CsvStore, user: dict, team_id: str) -> set[str] | None:
    """None means unrestricted; otherwise the only subteam IDs the user may read."""
    if can_view_all(user):
        return None
    return await membership_ids(db, team_id, user["user_id"])


async def assignable_members(db: CsvStore, team_id: str, subteam_id: str) -> list[dict[str, Any]]:
    people = {
        row.get("user_id", ""): row
        for row in await db.query("users")
        if row.get("team_id") == team_id and row.get("status") == "active"
    }
    result = []
    for member in await members_for(db, team_id, subteam_id):
        person = people.get(member.get("user_id", ""))
        if person is None:
            continue
        result.append({
            **member,
            "name": person.get("name", ""),
            "email": person.get("email", ""),
            "role": member.get("role", "volunteer"),
        })
    return result


async def is_last_coordinator(db: CsvStore, team_id: str, subteam_id: str, user_id: str) -> bool:
    rows = await db.query("subteam_members", team_id)
    coordinators = [
        row for row in rows
        if row.get("subteam_id") == subteam_id and row.get("role") == "coordinator"
    ]
    return len(coordinators) <= 1 and any(row.get("user_id") == user_id for row in coordinators)


async def add_membership(
    db: CsvStore,
    team_id: str,
    subteam_id: str,
    user_id: str,
    role: str,
    added_by: str = "",
) -> bool:
    """Add one membership. Returns False when the person is already in the subteam."""
    if role not in SUBTEAM_ROLES:
        raise ValueError(f"Unknown subteam role: {role}")
    rows = await db.query("subteam_members", team_id)
    if any(row.get("subteam_id") == subteam_id and row.get("user_id") == user_id for row in rows):
        return False
    await db.insert(
        "subteam_members",
        {
            "subteam_id": subteam_id,
            "user_id": user_id,
            "role": role,
            "added_by": added_by,
            "added_at": now_iso(),
        },
        team_id,
    )
    return True


async def remove_membership(db: CsvStore, team_id: str, subteam_id: str, user_id: str) -> bool:
    rows = await db.query("subteam_members", team_id)
    if not any(row.get("subteam_id") == subteam_id and row.get("user_id") == user_id for row in rows):
        return False

    def remove(items: list[dict]) -> list[dict]:
        return [
            row for row in items
            if not (row.get("subteam_id") == subteam_id and row.get("user_id") == user_id)
        ]

    await db.mutate("subteam_members", remove, team_id)
    return True


async def set_membership_role(db: CsvStore, team_id: str, subteam_id: str, user_id: str, role: str) -> bool:
    if role not in SUBTEAM_ROLES:
        raise ValueError(f"Unknown subteam role: {role}")
    rows = await db.query("subteam_members", team_id)
    target = next(
        (row for row in rows if row.get("subteam_id") == subteam_id and row.get("user_id") == user_id),
        None,
    )
    if target is None:
        return False

    def update(items: list[dict]) -> list[dict]:
        for row in items:
            if row.get("subteam_id") == subteam_id and row.get("user_id") == user_id:
                row["role"] = role
        return items

    await db.mutate("subteam_members", update, team_id)
    return True


async def members_for(db: CsvStore, team_id: str, subteam_id: str) -> list[dict[str, Any]]:
    return [
        row for row in await db.query("subteam_members", team_id)
        if row.get("subteam_id") == subteam_id
    ]
