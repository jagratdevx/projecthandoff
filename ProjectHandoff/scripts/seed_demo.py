#!/usr/bin/env python3
"""Seed realistic demo data into a LOCAL storage backend.

For designers & contributors: gives you a full-looking app (team, members,
projects, tasks, events, handovers, activity) to design and build against —
no Google account, no Drive, no OAuth needed.

Safety: refuses to run unless PH_STORAGE_MODE=local, so it can never write
demo rows into anyone's real Google Drive. Data lands in the gitignored
`data/` directory and can be wiped by deleting it.

Usage:
    PH_STORAGE_MODE=local backend/.venv/bin/python scripts/seed_demo.py

Then run the backend and frontend and sign in:
    owner:    maya@example.com   / demo1234
    members:  arjun@example.com, priya@example.com, dev@example.com, sara@example.com  / demo1234
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Hard guard: this script must never touch a Drive-backed deployment.
if os.environ.get("PH_STORAGE_MODE", "").lower() not in ("local", "auto"):
    sys.exit("Refusing to run: set PH_STORAGE_MODE=local first (this seeds local demo data only).")
if os.environ.get("PH_STORAGE_MODE", "").lower() == "auto":
    os.environ["PH_STORAGE_MODE"] = "local"

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))

from app.config import Settings  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.csvstore import CsvStore  # noqa: E402
from app.services.drive.factory import create_drive_backend  # noqa: E402

TEAM_NAME = "Studio Relay"
MEMBERS = [  # (name, email, role)
    ("Maya Iyer", "maya@example.com", "owner"),
    ("Arjun Rao", "arjun@example.com", "admin"),
    ("Priya Nair", "priya@example.com", "member"),
    ("Dev Menon", "dev@example.com", "member"),
    ("Sara Khan", "sara@example.com", "member"),
]
PASSWORD = "demo1234"


def uid() -> str:
    return str(uuid.uuid4())


def iso(days_offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_offset)).isoformat()


async def main() -> None:
    settings = Settings()
    backend = create_drive_backend(settings)
    if backend.mode != "local":
        sys.exit(f"Refusing to run: backend resolved to '{backend.mode}' (must be local).")
    store = CsvStore(backend)
    await store.init()

    # Idempotency: skip if a demo team already exists.
    existing, _ = await store.read("teams")
    if any(t.get("name") == TEAM_NAME for t in existing):
        print("Demo data already present — nothing to do. Delete the data/ directory to start fresh.")
        return

    team_id = uid()
    user_ids: dict[str, str] = {}
    for name, email, role in MEMBERS:
        user_ids[email] = uid()
        await store.insert("users", {
            "user_id": user_ids[email], "name": name, "email": email,
            "role": role, "team_id": team_id, "joined_at": iso(-30), "status": "active",
        })
        await store.insert("credentials", {
            "user_id": user_ids[email], "password_hash": hash_password(PASSWORD),
            "created_at": iso(-30),
        })
    await store.ensure_team(team_id)
    owner = user_ids["maya@example.com"]

    await store.insert("teams", {
        "team_id": team_id, "name": TEAM_NAME,
        "description": "Design demo team — a product studio coordinating handovers.",
        "owner_id": owner, "created_at": iso(-30), "status": "active",
        "drive_folder_id": "", "drive_folder_url": "",
    })

    # Projects
    projects: dict[str, str] = {}
    for name, desc, status, prio, start, deadline in (
        ("Mobile App Redesign", "Full visual + interaction overhaul of the mobile app.", "Active", "High", -20, 12),
        ("Marketing Website", "New public site: landing, pricing, blog.", "Active", "Medium", -10, 25),
        ("Onboarding Flow", "First-run experience for new workspaces.", "Planning", "Low", 5, 40),
    ):
        pid = uid()
        projects[name] = pid
        await store.insert("projects", {
            "project_id": pid, "name": name, "description": desc, "owner_id": owner,
            "start_date": iso(start), "deadline": iso(deadline), "status": status,
            "priority": prio, "created_at": iso(start), "updated_at": iso(-1),
        }, team_id=team_id)

    # Events + departments + members
    event_id = uid()
    await store.insert("events", {
        "event_id": event_id, "name": "Launch Week", "description": "Release event for the redesigned app.",
        "start_date": iso(18), "end_date": iso(20), "owner_id": owner,
        "status": "Planning", "created_at": iso(-5),
    }, team_id=team_id)
    dept_ids: dict[str, str] = {}
    for dept_name, coord in (("Design", "priya@example.com"), ("Engineering", "dev@example.com")):
        did = uid()
        dept_ids[dept_name] = did
        await store.insert("departments", {
            "department_id": did, "event_id": event_id, "name": dept_name,
            "coordinator_id": user_ids[coord], "description": f"{dept_name} workstream for Launch Week.",
            "status": "Active",
        }, team_id=team_id)
        await store.insert("department_members", {
            "department_id": did, "user_id": user_ids[coord],
            "added_by": owner, "added_at": iso(-4),
        }, team_id=team_id)

    # Tasks — a mix of statuses/priorities/deadlines (incl. overdue & upcoming)
    task_plan = [
        ("Audit existing screens", "Design", 0, "Completed", "High", -14),
        ("New color system", "Design", 0, "In Progress", "High", 2),
        ("Component library pass", "Design", 0, "In Progress", "Medium", 6),
        ("Dark-mode contrast check", "Design", 1, "To Do", "Medium", 9),
        ("Refactor navigation shell", "Engineering", 0, "In Progress", "Critical", 1),
        ("Migrate table component", "Engineering", 1, "To Do", "Medium", 8),
        ("Fix layout shift on load", "Engineering", 1, "Blocked", "High", -2),
        ("Set up analytics events", "", 2, "To Do", "Low", 15),
        ("Write launch checklist", "", 2, "To Do", "Medium", 12),
    ]
    task_ids: list[str] = []
    for title, dept, proj_idx, status, prio, deadline in task_plan:
        tid = uid()
        task_ids.append(tid)
        await store.insert("tasks", {
            "task_id": tid, "project_id": list(projects.values())[proj_idx],
            "event_id": "", "department_id": dept_ids.get(dept, ""),
            "title": title, "description": f"Demo task — {title.lower()}.",
            "assigned_to": list(user_ids.values())[len(task_ids) % len(user_ids)],
            "created_by": owner, "priority": prio, "status": status,
            "deadline": iso(deadline), "version": "1",
            "created_at": iso(-7), "updated_at": iso(-1),
        }, team_id=team_id)

    # A pending handover so that screen has content
    await store.insert("handovers", {
        "handover_id": uid(), "task_id": task_ids[6],
        "previous_owner_id": user_ids["dev@example.com"],
        "proposed_owner_id": user_ids["sara@example.com"],
        "completed_work": "Diagnosed the CLS source to font swap; added explicit sizing.",
        "remaining_work": "Regression check on Safari; update the changelog entry.",
        "current_state": "Fix implemented on a branch, pending review.",
        "blockers": "Needs access to the analytics dashboard for before/after numbers.",
        "next_actions": "Review, merge, then monitor CLS in production for a week.",
        "relevant_files": "src/pages/Dashboard.tsx, src/index.css",
        "deadline": iso(3), "status": "pending", "created_at": iso(-1), "accepted_at": "",
    }, team_id=team_id)

    # Activity trail
    for i, (action, desc, who) in enumerate((
        ("project.created", "Maya created project Mobile App Redesign", "maya@example.com"),
        ("task.status_changed", "Arjun moved Fix layout shift on load to Blocked", "arjun@example.com"),
        ("comment.added", "Priya commented on New color system", "priya@example.com"),
        ("handover.proposed", "Dev proposed a handover to Sara", "dev@example.com"),
        ("member.joined", "Sara joined the team", "sara@example.com"),
    )):
        await store.insert("activity", {
            "activity_id": uid(), "team_id": team_id, "project_id": list(projects.values())[0],
            "task_id": "", "user_id": user_ids[who], "action": action,
            "description": desc, "timestamp": iso(-5 + i),
        }, team_id=team_id)

    counts = {t: len((await store.read(t, team_id))[0]) for t in ("projects", "events", "tasks", "handovers", "departments")}
    counts["users"] = len((await store.read("users"))[0])
    print(f"Demo data seeded into {settings.local_data_dir}")
    print("  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    print(f"\nSign in (any member): maya@example.com / {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
