from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.deps import CurrentUser, DbDep

router = APIRouter(prefix="/api/archive", tags=["archive"])


async def _check_access(db: DbDep, user: dict, team_id: str) -> dict:
    team = next((t for t in await db.query("teams") if t.get("team_id") == team_id), None)
    if team is None or team.get("status") != "archived":
        raise HTTPException(status_code=404, detail="Archived team not found")
    allowed = any(
        row.get("team_id") == team_id
        and row.get("user_id") == user["user_id"]
        and row.get("state") != "removed"
        for row in await db.query("team_memberships")
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Archived team not found")
    return team


async def _activity(
    db: DbDep,
    team_id: str,
    source: str,
    subteam_id: str,
    limit: int,
    offset: int,
) -> dict:
    rows = [
        row for row in await db.query("activity_log", team_id)
        if row.get("source") == source and (not subteam_id or row.get("subteam_id") == subteam_id)
    ]
    rows.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
    users = {u["user_id"]: u for u in await db.query("users")}
    items = []
    for entry in rows[offset : offset + limit]:
        item = dict(entry)
        item["user_name"] = users.get(entry.get("user_id", ""), {}).get("name", "")
        items.append(item)
    return {"items": items, "total": len(rows)}


@router.get("/{team_id}/activity")
async def archived_activity(
    team_id: str,
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await _check_access(db, user, team_id)
    return await _activity(db, team_id, "main", "", limit, offset)


@router.get("/{team_id}/subteams/{subteam_id}/activity")
async def archived_subteam_activity(
    team_id: str,
    subteam_id: str,
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await _check_access(db, user, team_id)
    return await _activity(db, team_id, "subteam", subteam_id, limit, offset)


@router.get("/{team_id}/summary")
async def archived_summary(team_id: str, user: CurrentUser, db: DbDep) -> dict:
    team = await _check_access(db, user, team_id)
    counts = {}
    for table in ("projects", "tasks", "handovers", "events", "subteams", "activity_log"):
        counts[table] = len(await db.query(table, team_id))
    return {
        "team": {
            "team_id": team.get("team_id", ""),
            "name": team.get("name", ""),
            "description": team.get("description", ""),
            "status": team.get("status", ""),
        },
        "counts": counts,
    }
