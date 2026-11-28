from __future__ import annotations

import logging

from app.services.csvstore import ACTIVITY_ROW_LIMIT, CsvStore, now_iso, new_id

logger = logging.getLogger("projecthandoff")

# Canonical activity actions (audit trail)
ACTION_TASK_CREATED = "task.created"
ACTION_TASK_UPDATED = "task.updated"
ACTION_TASK_DELETED = "task.deleted"
ACTION_TASK_STATUS = "task.status_changed"
ACTION_TASK_ASSIGNED = "task.assigned"
ACTION_HANDOVER_REQUESTED = "handover.requested"
ACTION_HANDOVER_ACCEPTED = "handover.accepted"
ACTION_HANDOVER_REJECTED = "handover.rejected"
ACTION_HANDOVER_CLARIFY = "handover.clarification_requested"
ACTION_HANDOVER_RESPONDED = "handover.responded"
ACTION_HANDOVER_CANCELLED = "handover.cancelled"
ACTION_PROJECT_CREATED = "project.created"
ACTION_PROJECT_UPDATED = "project.updated"
ACTION_PROJECT_ARCHIVED = "project.archived"
ACTION_EVENT_CREATED = "event.created"
ACTION_EVENT_UPDATED = "event.updated"
ACTION_DEPARTMENT_CREATED = "department.created"
ACTION_DEPARTMENT_UPDATED = "department.updated"
ACTION_SUBTEAM_CREATED = "subteam.created"
ACTION_SUBTEAM_DELETED = "subteam.deleted"
ACTION_MEMBER_ADDED = "department.member_added"
ACTION_MEMBER_REMOVED = "department.member_removed"
ACTION_FILE_UPLOADED = "file.uploaded"
ACTION_FILE_DELETED = "file.deleted"
ACTION_COMMENT_ADDED = "comment.added"
ACTION_TEAM_UPDATED = "team.updated"
ACTION_TEAM_COMPLETED = "team.completed"
ACTION_MEMBER_JOINED = "team.member_joined"
ACTION_MEMBER_LEFT = "team.member_removed"
ACTION_ROLE_CHANGED = "team.role_changed"
ACTION_INVITE_CREATED = "team.invite_created"
ACTION_INVITE_REVOKED = "team.invite_revoked"
ACTION_DRIVE_FOLDER_CONNECTED = "team.drive_folder_connected"
ACTION_SUBTEAM_MEMBER_ADDED = "subteam.member_added"
ACTION_SUBTEAM_MEMBER_REMOVED = "subteam.member_removed"
ACTION_SUBTEAM_ROLE_CHANGED = "subteam.role_changed"
ACTION_SUBTEAM_INVITE_CREATED = "subteam.invite_created"
ACTION_SUBTEAM_MEMBER_JOINED = "subteam.member_joined"
ACTION_SUBTEAM_PROJECT_CREATED = "subteam.project_created"
ACTION_SUBTEAM_PROJECT_UPDATED = "subteam.project_updated"
ACTION_SUBTEAM_PROJECT_ARCHIVED = "subteam.project_archived"
ACTION_SUBTEAM_HANDOVER_REQUESTED = "subteam.handover_requested"
ACTION_SUBTEAM_HANDOVER_ACCEPTED = "subteam.handover_accepted"
ACTION_SUBTEAM_HANDOVER_REJECTED = "subteam.handover_rejected"
ACTION_SUBTEAM_HANDOVER_CLARIFY = "subteam.handover_clarification_requested"


async def log_activity(
    db: CsvStore,
    *,
    team_id: str,
    action: str,
    description: str,
    user_id: str = "",
    project_id: str = "",
    task_id: str = "",
    allow_archived: bool = False,
) -> None:
    """Append an audit entry to the global activity.csv (capped)."""
    if team_id and not allow_archived and await db.is_archived(team_id):
        return
    entry = {
        "activity_id": new_id(),
        "team_id": team_id,
        "project_id": project_id,
        "task_id": task_id,
        "user_id": user_id,
        "action": action,
        "description": description,
        "timestamp": now_iso(),
    }

    def fn(rows: list[dict]) -> list[dict]:
        rows.append(entry)
        return rows[-ACTIVITY_ROW_LIMIT:]

    await db.mutate("activity", fn)
    if team_id:
        await db.insert(
            "activity_log",
            {**entry, "subteam_id": "", "source": "main"},
            team_id,
            allow_archived=allow_archived,
        )

async def log_subteam_activity(
    db: CsvStore,
    *,
    team_id: str,
    subteam_id: str,
    action: str,
    description: str,
    summary: str,
    user_id: str = "",
    project_id: str = "",
    task_id: str = "",
    rollup: bool = True,
) -> None:
    """Append a detailed subteam entry and a brief main-feed roll-up."""
    if await db.is_archived(team_id):
        return
    entry = {
        "activity_id": new_id(),
        "team_id": team_id,
        "subteam_id": subteam_id,
        "project_id": project_id,
        "task_id": task_id,
        "user_id": user_id,
        "action": action,
        "description": description,
        "timestamp": now_iso(),
    }

    def fn(rows: list[dict]) -> list[dict]:
        rows.append(entry)
        return rows[-ACTIVITY_ROW_LIMIT:]

    await db.mutate("subteam_activity", fn, team_id)
    await db.insert("activity_log", {**entry, "source": "subteam"}, team_id)
    if rollup:
        try:
            await log_activity(
                db,
                team_id=team_id,
                action=f"subteam.{action.split('.', 1)[-1]}",
                description=summary,
                user_id=user_id,
                project_id=project_id,
                task_id=task_id,
            )
        except Exception as exc:  # noqa: BLE001 — roll-up must not fail the action
            logger.warning("Could not write subteam activity roll-up: %s", exc)
