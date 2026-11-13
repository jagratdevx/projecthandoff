from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.deps import CurrentUser, DbDep, require_team

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

UPCOMING_DAYS = 14


@router.get("")
async def dashboard(user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    today = datetime.now(timezone.utc).date()
    horizon = (today + timedelta(days=UPCOMING_DAYS)).isoformat()

    projects = await db.query("projects", team_id)
    tasks = await db.query("tasks", team_id)
    events = await db.query("events", team_id)
    departments = await db.query("departments", team_id)
    handovers = await db.query("handovers", team_id)
    members_rows = await db.query("department_members", team_id)
    users = [u for u in await db.query("users") if u.get("team_id") == team_id]
    names = {u["user_id"]: u["name"] for u in users}
    activity_rows = [a for a in await db.query("activity") if a.get("team_id") == team_id]

    def progress(items: list[dict]) -> dict:
        completed = sum(1 for t in items if t.get("status") == "Completed")
        return {"total": len(items), "completed": completed}

    active_projects = [p for p in projects if p.get("status") == "Active"]
    project_cards = []
    for p in sorted(active_projects, key=lambda x: x.get("deadline") or "9999"):
        p_tasks = [t for t in tasks if t.get("project_id") == p["project_id"]]
        project_cards.append({**p, "owner_name": names.get(p.get("owner_id", ""), ""), "progress": progress(p_tasks)})

    my_tasks = [
        t for t in tasks
        if t.get("assigned_to") == user["user_id"] and t.get("status") != "Completed"
    ]
    my_tasks.sort(key=lambda t: t.get("deadline") or "9999")

    upcoming = [
        t for t in tasks
        if t.get("deadline") and t.get("status") != "Completed" and today.isoformat() <= t["deadline"] <= horizon
    ]
    upcoming.sort(key=lambda t: t["deadline"])

    overdue = [
        t for t in tasks
        if t.get("deadline") and t.get("status") != "Completed" and t["deadline"] < today.isoformat()
    ]

    incoming = [h for h in handovers if h.get("proposed_owner_id") == user["user_id"] and h.get("status") in ("pending", "clarification_requested")]
    outgoing = [h for h in handovers if h.get("previous_owner_id") == user["user_id"] and h.get("status") in ("pending", "clarification_requested")]

    def handover_card(h: dict) -> dict:
        task = next((t for t in tasks if t.get("task_id") == h.get("task_id")), {})
        return {
            **h,
            "task_title": task.get("title", ""),
            "previous_owner_name": names.get(h.get("previous_owner_id", ""), ""),
            "proposed_owner_name": names.get(h.get("proposed_owner_id", ""), ""),
        }

    event_cards = []
    for e in sorted([e for e in events if e.get("status") != "Cancelled"], key=lambda x: x.get("start_date") or "9999"):
        e_tasks = [t for t in tasks if t.get("event_id") == e["event_id"]]
        event_cards.append({**e, "progress": progress(e_tasks)})

    department_cards = []
    for d in departments:
        if d.get("status") != "Active":
            continue
        d_tasks = [t for t in tasks if t.get("department_id") == d["department_id"]]
        department_cards.append({
            **d,
            "coordinator_name": names.get(d.get("coordinator_id", ""), ""),
            "member_count": sum(1 for m in members_rows if m.get("department_id") == d["department_id"]),
            "progress": progress(d_tasks),
        })

    recent_activity = sorted(activity_rows, key=lambda a: a.get("timestamp", ""), reverse=True)[:10]
    for a in recent_activity:
        a["user_name"] = names.get(a.get("user_id", ""), "")

    return {
        "stats": {
            "active_projects": len(active_projects),
            "my_open_tasks": len(my_tasks),
            "pending_handovers": len(incoming) + len(outgoing),
            "upcoming_deadlines": len(upcoming),
            "overdue_tasks": len(overdue),
            "team_size": len(users),
        },
        "projects": project_cards[:6],
        "my_tasks": my_tasks[:8],
        "upcoming_deadlines": [{**t, "assignee_name": names.get(t.get("assigned_to", ""), "")} for t in upcoming[:8]],
        "incoming_handovers": [handover_card(h) for h in incoming[:5]],
        "outgoing_handovers": [handover_card(h) for h in outgoing[:5]],
        "events": event_cards[:6],
        "departments": department_cards[:8],
        "activity": recent_activity,
    }
