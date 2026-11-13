from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import EventStatus, Priority, ProjectStatus, TaskStatus, Role

EMAIL_RE = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"


def _norm_date(value: str | None) -> str:
    """Accept YYYY-MM-DD only (empty allowed)."""
    if value is None:
        return ""
    value = value.strip()
    if not value:
        return ""
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("Dates must use the YYYY-MM-DD format")
    year, month, day = value.split("-")
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        raise ValueError("Dates must use the YYYY-MM-DD format")
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        raise ValueError("Invalid calendar date")
    return value


class DateField(str):
    pass


# ----------------------------- auth -----------------------------

class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=5, max_length=120, pattern=EMAIL_RE)
    password: str = Field(min_length=8, max_length=128)
    invite_token: str = ""

    @field_validator("name", "email")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TokenOut(BaseModel):
    token: str
    user: dict


# ----------------------------- teams -----------------------------

class TeamCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class TeamUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class MemberUpdateIn(BaseModel):
    role: Role | None = None
    status: Literal["active", "inactive"] | None = None


class InviteCreateIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE)
    role: Role = "member"

    @field_validator("role")
    @classmethod
    def not_owner(cls, v: Role) -> Role:
        if v == "owner":
            raise ValueError("Ownership cannot be granted through invitations")
        return v


# ----------------------------- projects -----------------------------

class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    owner_id: str = ""
    start_date: str = ""
    deadline: str = ""
    priority: Priority = "Medium"
    status: ProjectStatus = "Planning"

    @field_validator("start_date", "deadline")
    @classmethod
    def valid_date(cls, v: str) -> str:
        return _norm_date(v)


class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    owner_id: str | None = None
    start_date: str | None = None
    deadline: str | None = None
    priority: Priority | None = None
    status: ProjectStatus | None = None

    @field_validator("start_date", "deadline")
    @classmethod
    def valid_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _norm_date(v)


# ----------------------------- tasks -----------------------------

class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    project_id: str = ""
    event_id: str = ""
    department_id: str = ""
    assigned_to: str = ""
    priority: Priority = "Medium"
    status: TaskStatus = "Not Started"
    deadline: str = ""

    @field_validator("deadline")
    @classmethod
    def valid_date(cls, v: str) -> str:
        return _norm_date(v)


class TaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    assigned_to: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    deadline: str | None = None
    project_id: str | None = None
    event_id: str | None = None
    department_id: str | None = None

    @field_validator("deadline")
    @classmethod
    def valid_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _norm_date(v)


class CommentIn(BaseModel):
    comment: str = Field(min_length=1, max_length=4000)


# ----------------------------- handovers -----------------------------

class HandoverCreateIn(BaseModel):
    task_id: str
    proposed_owner_id: str
    completed_work: str = Field(min_length=1, max_length=4000)
    remaining_work: str = Field(default="", max_length=4000)
    current_state: str = Field(default="", max_length=4000)
    blockers: str = Field(default="", max_length=4000)
    next_actions: str = Field(default="", max_length=4000)
    relevant_files: str = Field(default="", max_length=1000)
    deadline: str = ""
    notes: str = Field(default="", max_length=2000)

    @field_validator("deadline")
    @classmethod
    def valid_date(cls, v: str) -> str:
        return _norm_date(v)


class HandoverRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class HandoverClarifyIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class HandoverRespondIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


# ----------------------------- events -----------------------------

class EventCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    start_date: str = ""
    end_date: str = ""
    status: EventStatus = "Planning"

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        return _norm_date(v)


class EventUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: EventStatus | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _norm_date(v)


class DepartmentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    coordinator_id: str = ""
    description: str = Field(default="", max_length=1000)


class DepartmentUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    coordinator_id: str | None = None
    description: str | None = None
    status: Literal["Active", "Archived"] | None = None


class DepartmentMemberIn(BaseModel):
    user_id: str = Field(min_length=1)
