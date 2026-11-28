from __future__ import annotations

from typing import Any

from app.services.csvstore import CsvStore
from app.services.drive.base import DriveError
from app.services.drive.google_drive import GoogleDriveBackend
from app.services.drive_link import drive_folder_url


async def _team(db: CsvStore, team_id: str) -> dict | None:
    return next((row for row in await db.query("teams") if row.get("team_id") == team_id), None)


async def resources_folder_for(db: CsvStore, team_id: str) -> str:
    """Return (and create if needed) the folder members are allowed to see."""
    team = await _team(db, team_id)
    if team is None or not team.get("drive_folder_id"):
        return ""
    existing = team.get("resources_folder_id", "")
    if existing:
        return existing
    try:
        folder_id = await db.backend.ensure_folder(f"Resources/{team_id}")
    except DriveError:
        return ""

    def store(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("team_id") == team_id:
                row["resources_folder_id"] = folder_id
                row["resources_folder_url"] = (
                    drive_folder_url(folder_id)
                    if db.backend.mode == "drive" and folder_id and "/" not in folder_id
                    else ""
                )
        return rows

    await db.mutate("teams", store)
    return folder_id


async def _call_share(backend: Any, team_id: str, folder_id: str, email: str, role: str) -> None:
    if isinstance(backend, GoogleDriveBackend):
        await backend.team_share_folder(team_id, folder_id, email, role=role)
    else:
        await backend.share_folder(folder_id, email, role=role)


async def _call_unshare(backend: Any, team_id: str, folder_id: str, email: str) -> None:
    if isinstance(backend, GoogleDriveBackend):
        await backend.team_unshare_folder(team_id, folder_id, email)
    else:
        await backend.unshare_folder(folder_id, email)


async def share_resources_with_member(
    db: CsvStore, team_id: str, email: str, role: str = "writer"
) -> bool:
    """Grant access to Resources only; remove inherited access to the team root."""
    if not email:
        return False
    folder_id = await resources_folder_for(db, team_id)
    if not folder_id:
        return False
    try:
        await _call_share(db.backend, team_id, folder_id, email, role)
    except DriveError:
        return False
    team = await _team(db, team_id)
    root_id = team.get("drive_folder_id", "") if team else ""
    if root_id and root_id != folder_id:
        try:
            await _call_unshare(db.backend, team_id, root_id, email)
        except DriveError:
            pass
    return True


async def unshare_resources_from_member(db: CsvStore, team_id: str, email: str) -> None:
    if not email:
        return
    team = await _team(db, team_id)
    root_id = team.get("drive_folder_id", "") if team else ""
    resource_id = team.get("resources_folder_id", "") if team else ""
    for folder_id in {root_id, resource_id} - {""}:
        try:
            await _call_unshare(db.backend, team_id, folder_id, email)
        except DriveError:
            pass


async def sync_resource_sharing(db: CsvStore) -> int:
    """One-time migration: move existing members from team root to Resources."""
    synced = 0
    for team in await db.query("teams"):
        team_id = team.get("team_id", "")
        if not team_id or team.get("status") != "active" or not team.get("drive_folder_id"):
            continue
        if team.get("resources_folder_id"):
            continue
        for user in await db.query("users"):
            if user.get("team_id") != team_id or user.get("status") != "active":
                continue
            if await share_resources_with_member(db, team_id, user.get("email", "")):
                synced += 1
    return synced
