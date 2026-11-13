from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbDep, require_team
from app.services.activity import log_activity
from app.services.csvstore import now_iso

router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/activity")
async def list_activity(
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    team_id = require_team(user)
    rows = [a for a in await db.query("activity") if a.get("team_id") == team_id]
    rows.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    users = {u["user_id"]: u for u in await db.query("users") if u.get("team_id") == team_id}
    items = []
    for entry in rows[offset : offset + limit]:
        item = dict(entry)
        item["user_name"] = users.get(entry.get("user_id", ""), {}).get("name", "")
        items.append(item)
    return {"items": items, "total": len(rows)}
