from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser, DbDep, require_team
from app.services.subteams import coordinator_of, get_subteam, has_full_access, members_for
from app.schemas.api import (
    HandoverClarifyIn,
    HandoverCreateIn,
    HandoverRejectIn,
    HandoverRespondIn,
)
from app.services.activity import (
    ACTION_HANDOVER_ACCEPTED,
    ACTION_HANDOVER_CANCELLED,
    ACTION_HANDOVER_CLARIFY,
    ACTION_HANDOVER_REJECTED,
    ACTION_HANDOVER_REQUESTED,
    ACTION_HANDOVER_RESPONDED,
    ACTION_TASK_ASSIGNED,
    ACTION_SUBTEAM_HANDOVER_ACCEPTED,
    ACTION_SUBTEAM_HANDOVER_CLARIFY,
    ACTION_SUBTEAM_HANDOVER_REJECTED,
    ACTION_SUBTEAM_HANDOVER_REQUESTED,
    log_activity,
    log_subteam_activity,
)
from app.services.csvstore import now_iso, new_id

router = APIRouter(prefix="/api/handovers", tags=["handovers"])


async def _get_handover(db: DbDep, user: CurrentUser, handover_id: str) -> dict:
    team_id = require_team(user)
    handovers = await db.query("handovers", team_id)
    handover = next((h for h in handovers if h.get("handover_id") == handover_id), None)
    if handover is None:
        raise HTTPException(status_code=404, detail="Handover not found")
    return handover


async def _add_task_comment(db: DbDep, team_id: str, task: dict, user_id: str, text: str) -> None:
    await db.insert(
        "comments",
        {
            "comment_id": new_id(),
            "task_id": task["task_id"],
            "user_id": user_id,
            "comment": text,
            "created_at": now_iso(),
        },
        team_id,
    )


async def _can_approve(db: DbDep, user: CurrentUser, handover: dict, team_id: str) -> bool:
    if handover.get("proposed_owner_id") == user["user_id"] or has_full_access(user):
        return True
    subteam_id = handover.get("subteam_id", "")
    return bool(subteam_id) and subteam_id in await coordinator_of(db, team_id, user["user_id"])


async def _log_handover_event(
    db: DbDep,
    team_id: str,
    handover: dict,
    task: dict,
    user_id: str,
    *,
    main_action: str,
    subteam_action: str,
    description: str,
    subteam_name: str,
) -> None:
    subteam_id = handover.get("subteam_id", "")
    if subteam_id:
        await log_subteam_activity(
            db, team_id=team_id, subteam_id=subteam_id,
            action=subteam_action, description=description,
            summary=f"“{subteam_name or 'Subteam'}”: {description.split(' ', 1)[-1]}",
            user_id=user_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
        )
    else:
        await log_activity(
            db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
            action=main_action, description=description, user_id=user_id,
        )


@router.get("")
async def list_handovers(
    user: CurrentUser,
    db: DbDep,
    direction: str = "team",
    status: str = "",
    task_id: str = "",
) -> list[dict]:
    team_id = require_team(user)
    handovers = await db.query("handovers", team_id)
    if direction == "incoming":
        handovers = [h for h in handovers if h.get("proposed_owner_id") == user["user_id"]]
    elif direction == "outgoing":
        handovers = [h for h in handovers if h.get("previous_owner_id") == user["user_id"]]
    if status:
        handovers = [h for h in handovers if h.get("status") == status]
    if task_id:
        handovers = [h for h in handovers if h.get("task_id") == task_id]
    tasks = {t["task_id"]: t for t in await db.query("tasks", team_id)}
    users = {u["user_id"]: u for u in await db.query("users") if u.get("team_id") == team_id}
    subteams = {s["subteam_id"]: s.get("name", "") for s in await db.query("subteams", team_id)}

    enriched = []
    for h in handovers:
        item = dict(h)
        task = tasks.get(h.get("task_id", ""))
        item["task_title"] = task.get("title", "") if task else "(deleted task)"
        item["previous_owner_name"] = users.get(h.get("previous_owner_id", ""), {}).get("name", "Unknown")
        item["proposed_owner_name"] = users.get(h.get("proposed_owner_id", ""), {}).get("name", "Unknown")
        item["subteam_name"] = subteams.get(h.get("subteam_id", ""), "")
        item["can_approve"] = await _can_approve(db, user, h, team_id)
        enriched.append(item)
    enriched.sort(key=lambda h: h.get("created_at", ""), reverse=True)
    return enriched


@router.post("", status_code=201)
async def create_handover(payload: HandoverCreateIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == payload.task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    is_admin = has_full_access(user)
    if task.get("assigned_to") != user["user_id"] and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only the current assignee (or a team admin) can hand this task over",
        )
    users = await db.query("users")
    proposed = next(
        (u for u in users if u.get("user_id") == payload.proposed_owner_id and u.get("team_id") == team_id and u.get("status") == "active"),
        None,
    )
    if proposed is None:
        raise HTTPException(status_code=400, detail="Proposed owner must be an active member of your team")
    scoped_id = payload.subteam_id or task.get("subteam_id", "")
    if scoped_id and not any(
        row.get("user_id") == payload.proposed_owner_id
        for row in await members_for(db, team_id, scoped_id)
    ):
        raise HTTPException(status_code=400, detail="Proposed owner must be a member of this subteam")
    if payload.proposed_owner_id == task.get("assigned_to"):
        raise HTTPException(status_code=400, detail="The task is already assigned to this member")

    open_handovers = await db.query("handovers", team_id)
    if any(
        h.get("task_id") == payload.task_id and h.get("status") in ("pending", "clarification_requested")
        for h in open_handovers
    ):
        raise HTTPException(status_code=409, detail="This task already has an open handover")

    subteam_id = payload.subteam_id or task.get("subteam_id", "")
    subteam = await get_subteam(db, team_id, subteam_id) if subteam_id else None
    if subteam_id and subteam is None:
        raise HTTPException(status_code=400, detail="That subteam does not belong to your team")

    handover = {
        "handover_id": new_id(),
        "task_id": payload.task_id,
        "previous_owner_id": task.get("assigned_to") or user["user_id"],
        "proposed_owner_id": payload.proposed_owner_id,
        "completed_work": payload.completed_work.strip(),
        "remaining_work": payload.remaining_work.strip(),
        "current_state": payload.current_state.strip(),
        "blockers": payload.blockers.strip(),
        "next_actions": payload.next_actions.strip(),
        "relevant_files": payload.relevant_files.strip(),
        "deadline": payload.deadline,
        "status": "pending",
        "created_at": now_iso(),
        "accepted_at": "",
        "subteam_id": subteam_id,
    }
    await db.insert("handovers", handover, team_id)
    if payload.notes.strip():
        await _add_task_comment(
            db, team_id, task, user["user_id"],
            f"Handover notes: {payload.notes.strip()}",
        )
    description = f"{user['name']} requested a handover of “{task['title']}” to {proposed['name']}"
    if subteam:
        await log_subteam_activity(
            db, team_id=team_id, subteam_id=subteam_id,
            action=ACTION_SUBTEAM_HANDOVER_REQUESTED,
            description=description,
            summary=f"“{subteam.get('name', 'Subteam')}”: handover of “{task['title']}” requested",
            user_id=user["user_id"], project_id=task.get("project_id", ""), task_id=task["task_id"],
        )
    else:
        await log_activity(
            db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
            action=ACTION_HANDOVER_REQUESTED,
            description=description,
            user_id=user["user_id"],
        )
    return handover


@router.get("/{handover_id}")
async def get_handover(handover_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    handover = await _get_handover(db, user, handover_id)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == handover["task_id"]), None)
    comments = (
        sorted(
            [c for c in await db.query("comments", team_id) if c.get("task_id") == handover["task_id"]],
            key=lambda c: c.get("created_at", ""),
        )
        if task
        else []
    )
    attachments = (
        [a for a in await db.query("attachments", team_id) if a.get("task_id") == handover["task_id"]]
        if task
        else []
    )
    users = {u["user_id"]: u for u in await db.query("users") if u.get("team_id") == team_id}
    subteam_id = handover.get("subteam_id", "")
    subteam = await get_subteam(db, team_id, subteam_id) if subteam_id else None
    detail = dict(handover)
    detail["subteam_name"] = subteam.get("name", "") if subteam else ""
    detail["can_approve"] = await _can_approve(db, user, handover, team_id)
    return {
        "handover": detail,
        "task": task,
        "comments": comments,
        "attachments": attachments,
        "names": {uid: u["name"] for uid, u in users.items()},
    }


@router.post("/{handover_id}/accept")
async def accept_handover(handover_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    handover = await _get_handover(db, user, handover_id)
    if not await _can_approve(db, user, handover, team_id):
        raise HTTPException(status_code=403, detail="Only the proposed owner, a team overseer or this subteam's coordinator can accept this handover")
    if handover.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"This handover is {handover.get('status')} and cannot be accepted")

    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == handover["task_id"]), None)
    if task is None:
        raise HTTPException(status_code=404, detail="The task for this handover no longer exists")

    def update_handover(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("handover_id") == handover_id:
                row["status"] = "accepted"
                row["accepted_at"] = now_iso()
                return rows
        raise HTTPException(status_code=404, detail="Handover not found")

    proposed_id = handover["proposed_owner_id"]
    proposed_name = next(
        (u.get("name", "") for u in await db.query("users") if u.get("user_id") == proposed_id),
        "the proposed owner",
    )

    def update_task(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("task_id") == handover["task_id"]:
                row["assigned_to"] = proposed_id
                row["version"] = str(int(row.get("version", "0") or "0") + 1)
                row["updated_at"] = now_iso()
                return rows
        raise HTTPException(status_code=404, detail="Task not found")

    await db.mutate("handovers", update_handover, team_id)
    await db.mutate("tasks", update_task, team_id)
    await _add_task_comment(
        db, team_id, task, user["user_id"],
        f"Accepted the handover from {handover['previous_owner_id']} to {proposed_id}.",
    )
    subteam_id = handover.get("subteam_id", "")
    subteam = await get_subteam(db, team_id, subteam_id) if subteam_id else None
    accepted_description = f"{user['name']} accepted the handover of “{task['title']}” to {proposed_name}"
    if subteam:
        await log_subteam_activity(
            db, team_id=team_id, subteam_id=subteam_id,
            action=ACTION_SUBTEAM_HANDOVER_ACCEPTED,
            description=accepted_description,
            summary=f"“{subteam.get('name', 'Subteam')}”: handover of “{task['title']}” approved",
            user_id=user["user_id"], project_id=task.get("project_id", ""), task_id=task["task_id"],
        )
    else:
        await log_activity(
            db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
            action=ACTION_HANDOVER_ACCEPTED,
            description=accepted_description,
            user_id=user["user_id"],
        )
    await log_activity(
        db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
        action=ACTION_TASK_ASSIGNED,
        description=f"“{task['title']}” is now assigned to {proposed_name}",
        user_id=user["user_id"],
    )
    return {"ok": True, "task": {**task, "assigned_to": proposed_id}}


@router.post("/{handover_id}/reject")
async def reject_handover(handover_id: str, payload: HandoverRejectIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    handover = await _get_handover(db, user, handover_id)
    if not await _can_approve(db, user, handover, team_id):
        raise HTTPException(status_code=403, detail="Only the proposed owner, a team overseer or this subteam's coordinator can reject this handover")
    if handover.get("status") not in ("pending", "clarification_requested"):
        raise HTTPException(status_code=409, detail=f"This handover is already {handover.get('status')}")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("handover_id") == handover_id:
                row["status"] = "rejected"
                return rows
        raise HTTPException(status_code=404, detail="Handover not found")

    await db.mutate("handovers", fn, team_id)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == handover["task_id"]), None)
    if task is not None:
        await _add_task_comment(
            db, team_id, task, user["user_id"],
            f"Rejected the handover. Reason: {payload.reason.strip()}",
        )
        subteam_id = handover.get("subteam_id", "")
        subteam = await get_subteam(db, team_id, subteam_id) if subteam_id else None
        await _log_handover_event(
            db, team_id, handover, task, user["user_id"],
            main_action=ACTION_HANDOVER_REJECTED,
            subteam_action=ACTION_SUBTEAM_HANDOVER_REJECTED,
            description=f"{user['name']} rejected the handover of “{task['title']}”",
            subteam_name=subteam.get("name", "") if subteam else "",
        )
    # Ownership intentionally NOT transferred on rejection.
    return {"ok": True}


@router.post("/{handover_id}/clarify")
async def request_clarification(handover_id: str, payload: HandoverClarifyIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    handover = await _get_handover(db, user, handover_id)
    if not await _can_approve(db, user, handover, team_id):
        raise HTTPException(status_code=403, detail="Only the proposed owner, a team overseer or this subteam's coordinator can request clarification")
    if handover.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"This handover is already {handover.get('status')}")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("handover_id") == handover_id:
                row["status"] = "clarification_requested"
                return rows
        raise HTTPException(status_code=404, detail="Handover not found")

    await db.mutate("handovers", fn, team_id)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == handover["task_id"]), None)
    if task is not None:
        await _add_task_comment(
            db, team_id, task, user["user_id"],
            f"Clarification requested: {payload.question.strip()}",
        )
        subteam_id = handover.get("subteam_id", "")
        subteam = await get_subteam(db, team_id, subteam_id) if subteam_id else None
        await _log_handover_event(
            db, team_id, handover, task, user["user_id"],
            main_action=ACTION_HANDOVER_CLARIFY,
            subteam_action=ACTION_SUBTEAM_HANDOVER_CLARIFY,
            description=f"{user['name']} asked for clarification on the handover of “{task['title']}”",
            subteam_name=subteam.get("name", "") if subteam else "",
        )
    return {"ok": True}


@router.post("/{handover_id}/respond")
async def respond_to_clarification(handover_id: str, payload: HandoverRespondIn, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    handover = await _get_handover(db, user, handover_id)
    is_admin = has_full_access(user)
    if handover.get("previous_owner_id") != user["user_id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Only the previous owner can respond to this handover")
    if handover.get("status") != "clarification_requested":
        raise HTTPException(status_code=409, detail="This handover is not awaiting clarification")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("handover_id") == handover_id:
                row["status"] = "pending"
                return rows
        raise HTTPException(status_code=404, detail="Handover not found")

    await db.mutate("handovers", fn, team_id)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == handover["task_id"]), None)
    if task is not None:
        await _add_task_comment(
            db, team_id, task, user["user_id"],
            f"Clarification response: {payload.message.strip()}",
        )
        await log_activity(
            db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
            action=ACTION_HANDOVER_RESPONDED,
            description=f"{user['name']} responded to the clarification on “{task['title']}”",
            user_id=user["user_id"],
        )
    return {"ok": True}


@router.post("/{handover_id}/cancel")
async def cancel_handover(handover_id: str, user: CurrentUser, db: DbDep) -> dict:
    team_id = require_team(user)
    handover = await _get_handover(db, user, handover_id)
    is_admin = has_full_access(user)
    if handover.get("previous_owner_id") != user["user_id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Only the previous owner can cancel this handover")
    if handover.get("status") not in ("pending", "clarification_requested"):
        raise HTTPException(status_code=409, detail="This handover is already resolved")

    def fn(rows: list[dict]) -> list[dict]:
        for row in rows:
            if row.get("handover_id") == handover_id:
                row["status"] = "cancelled"
                return rows
        raise HTTPException(status_code=404, detail="Handover not found")

    await db.mutate("handovers", fn, team_id)
    tasks = await db.query("tasks", team_id)
    task = next((t for t in tasks if t.get("task_id") == handover["task_id"]), None)
    if task is not None:
        await log_activity(
            db, team_id=team_id, project_id=task.get("project_id", ""), task_id=task["task_id"],
            action=ACTION_HANDOVER_CANCELLED,
            description=f"{user['name']} cancelled the handover of “{task['title']}”",
            user_id=user["user_id"],
        )
    return {"ok": True}
