from __future__ import annotations

from app.services.csvstore import ACTIVITY_ROW_LIMIT, CsvStore, now_iso, new_id

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
ACTION_MEMBER_ADDED = "department.member_added"
ACTION_MEMBER_REMOVED = "department.member_removed"
ACTION_FILE_UPLOADED = "file.uploaded"
ACTION_FILE_DELETED = "file.deleted"
ACTION_COMMENT_ADDED = "comment.added"
ACTION_TEAM_UPDATED = "team.updated"
ACTION_MEMBER_JOINED = "team.member_joined"
ACTION_MEMBER_LEFT = "team.member_removed"
ACTION_ROLE_CHANGED = "team.role_changed"
ACTION_INVITE_CREATED = "team.invite_created"
ACTION_INVITE_REVOKED = "team.invite_revoked"
ACTION_DRIVE_FOLDER_CONNECTED = "team.drive_folder_connected"


async def log_activity(
    db: CsvStore,
    *,
    team_id: str,
    action: str,
    description: str,
    user_id: str = "",
    project_id: str = "",
    task_id: str = "",
) -> None:
    """Append an audit entry to the global activity.csv (capped)."""
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
