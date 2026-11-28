from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["owner", "admin", "council", "teacher", "coordinator", "member"]
SubteamRole = Literal["coordinator", "volunteer"]
UserStatus = Literal["active", "inactive"]
TeamStatus = Literal["active", "archived"]
ProjectStatus = Literal["Planning", "Active", "On Hold", "Completed", "Archived"]
EventStatus = Literal["Planning", "Active", "Completed", "Cancelled"]
DeptStatus = Literal["Active", "Archived"]
Priority = Literal["Low", "Medium", "High", "Critical"]
TaskStatus = Literal["Not Started", "In Progress", "Blocked", "Under Review", "Completed"]
HandoverStatus = Literal["pending", "clarification_requested", "accepted", "rejected", "cancelled"]
InviteStatus = Literal["pending", "accepted", "revoked", "expired"]

_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
DateStr = str  # validated with pattern via Field


class UserOut(BaseModel):
    user_id: str
    name: str
    email: str
    role: Role = "member"
    team_id: str = ""
    joined_at: str = ""
    status: UserStatus = "active"


class TeamOut(BaseModel):
    team_id: str
    name: str
    description: str = ""
    owner_id: str
    created_at: str = ""
    status: TeamStatus = "active"


class ProjectOut(BaseModel):
    project_id: str
    name: str
    description: str = ""
    owner_id: str = ""
    start_date: str = ""
    deadline: str = ""
    status: ProjectStatus = "Planning"
    priority: Priority = "Medium"
    created_at: str = ""
    updated_at: str = ""
    subteam_id: str = ""
    requirements: str = ""


class TaskOut(BaseModel):
    task_id: str
    project_id: str = ""
    event_id: str = ""
    department_id: str = ""
    title: str
    description: str = ""
    assigned_to: str = ""
    created_by: str = ""
    priority: Priority = "Medium"
    status: TaskStatus = "Not Started"
    deadline: str = ""
    version: str = "0"
    created_at: str = ""
    updated_at: str = ""
    subteam_id: str = ""


class HandoverOut(BaseModel):
    handover_id: str
    task_id: str
    previous_owner_id: str
    proposed_owner_id: str
    completed_work: str = ""
    remaining_work: str = ""
    current_state: str = ""
    blockers: str = ""
    next_actions: str = ""
    relevant_files: str = ""
    deadline: str = ""
    status: HandoverStatus = "pending"
    created_at: str = ""
    accepted_at: str = ""


class EventOut(BaseModel):
    event_id: str
    name: str
    description: str = ""
    start_date: str = ""
    end_date: str = ""
    owner_id: str = ""
    status: EventStatus = "Planning"
    created_at: str = ""


class DepartmentOut(BaseModel):
    department_id: str
    event_id: str
    name: str
    coordinator_id: str = ""
    description: str = ""
    status: DeptStatus = "Active"


class CommentOut(BaseModel):
    comment_id: str
    task_id: str
    user_id: str
    comment: str
    created_at: str


class ActivityOut(BaseModel):
    activity_id: str
    team_id: str
    project_id: str = ""
    task_id: str = ""
    user_id: str = ""
    action: str
    description: str = ""
    timestamp: str


class AttachmentOut(BaseModel):
    attachment_id: str
    task_id: str = ""
    project_id: str = ""
    drive_file_id: str
    file_name: str
    uploaded_by: str
    uploaded_at: str


class InvitationOut(BaseModel):
    invitation_id: str
    team_id: str
    email: str
    role: Role = "member"
    token_hash: str = Field(repr=False, default="")
    expires_at: str
    status: InviteStatus = "pending"
