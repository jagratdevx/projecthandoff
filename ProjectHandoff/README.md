# ProjectHandoff

A production-quality team coordination web app for student clubs — with a **structured task handover** workflow as its headline feature. Built with a React + TypeScript frontend and a FastAPI backend that uses **Google Drive as its only persistent store** (CSV files are the source of truth; uploads live in Drive folders).

> **Why Drive?** The team's data (members, projects, tasks, handovers, events, uploads) lives inside the team's own Google Drive. There is no server-side database: every record is a row in a CSV file, every upload is a Drive file, and the team owns all of it.

---

## Purpose — why this app exists

Every student club knows this cycle: a coordinator graduates, an event lead goes on exam leave, a project owner simply disappears — and with them goes **everything they knew**. Which sponsors were contacted? Where are the design files? What was left unfinished on the venue plan? The knowledge walks out the door because it was never *handed over*, it was just… somewhere: a WhatsApp message, a personal Drive folder, a notebook.

ProjectHandoff turns "handing over" into a **first-class, structured workflow** instead of a hallway conversation:

- Work is tracked as **tasks** with owners, deadlines and states — so "what's left?" always has an answer.
- When someone can't continue, they fill a **structured handover record** (completed work, remaining work, blockers, next actions, files…) and the receiver must explicitly **accept** it. Nothing silently changes hands.
- Every action lands in a **team activity feed** — an audit trail of who did what, when.
- And the club **owns its own data**: everything lives in a Google Drive folder the team controls, shared with the members. If the app server dies tomorrow, the data is still sitting in Drive as plain, readable CSVs and files. No vendor lock-in, no database server to maintain, no hosting fees for storage.

It is deliberately built to be run by *one person with a Google account and one small server* (a laptop, a Raspberry Pi, a free-tier VM) — not by a DevOps team.

### The storage philosophy, in one paragraph

Most apps put your data in someone else's database and give you an export button as an afterthought. ProjectHandoff inverts that: **Google Drive is the database**. CSV tables are human-readable, openable in Excel/Sheets, and backed up automatically on every write. Uploads are ordinary Drive files in the team's own folder, visible in Drive's normal UI. Members get real Drive access to the team folder — the app coordinates, but the club's files are never locked inside it.

---

## Features

- **Accounts & teams** — register, log in, create a team, invite members via single-use 7-day invite links (email must match on registration), role management (owner / admin / coordinator / member).
- **Bring-your-own Drive, per team** — at team creation the creator pastes their *own* Google OAuth client and connects their *own* Google account once; the team's folder link pins all the team's files and data tables inside their Drive, and every member gets writer access automatically (revoked when they're removed). Members never see Google anything — they just log in. Multi-tenant ready: every team owns its credentials, its folder and its data.
- **Projects** — list/create/archive projects with owners, priorities and progress.
- **Tasks** — full task lifecycle (Not Started → In Progress → Blocked → Under Review → Completed), assignees, deadlines, priorities, version-stamped updates, comments, attachments.
- **Structured handovers** — the core feature. A task owner hands a task to a teammate by filling a structured handover record: *completed work, remaining work, current state, blockers, next actions, relevant files, notes*. The proposed owner can **accept**, **reject** (with reason), or **request clarification**; the previous owner can **respond** or **cancel**. Every step is logged on the task as comments and in the team activity feed. Acceptance reassigns the task and bumps its version.
- **Events & departments** — events (fairs, competitions) split into departments (logistics, sponsors, tech…) with coordinators, members and per-department progress.
- **Attachments** — upload files to tasks, projects or events (type/size validated, stored in Drive folders).
- **Activity feed** — audit-style, reverse-chronological log of everything happening in the team.
- **Dashboard** — open tasks, pending handovers, upcoming/overdue deadlines, team size, recent activity.
- **Live-sync UX** — data refreshes right after your actions and polls the server every 10–15 s; a sync indicator shows transport health and the last successful sync. Requests for the screen you're on are prioritized over background syncing, and failed syncs retry themselves with backoff.
- **Bring-your-own Google Drive** — each team connects its own Google account once at team creation; members never see a Google prompt.
- **Light/dark theme**, responsive layout, accessible controls.

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Router, lucide-react |
| Backend | Python 3.14, FastAPI, Pydantic / pydantic-settings, google-api-python-client |
| Storage | Google Drive (each team's own account) — CSV data tables + upload folders. Optional single-organizer "host" mode and an explicit local-mode fallback for development. |
| Tests | pytest (backend, 117 tests), `tsc --noEmit` + production Vite build (frontend) |

---

## Quickstart (local development)

### 1. Backend

```bash
cd ProjectHandoff/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # set PH_STORAGE_MODE=drive for production; teams bring their own Google credentials at team creation
```

For **development without Google credentials** (explicit, opt-in local mode):

```bash
# in ProjectHandoff/.env
PH_STORAGE_MODE=local
PH_ALLOW_LOCAL_STORAGE=true
PH_SECRET_KEY=any-dev-secret
PH_LOCAL_DATA_DIR=            # optional; defaults to ProjectHandoff/data (gitignored)
```

Run it (from `ProjectHandoff/backend`):

```bash
.venv/bin/python -m uvicorn app.main:create_app --factory --port 8000
```

The backend never silently falls back between storage modes: `auto` requires Drive OAuth tokens to exist or startup fails with precise instructions; `drive` requires them outright; `local` requires the explicit `PH_ALLOW_LOCAL_STORAGE=true` opt-in and prints a prominent warning.

### 2. Frontend

```bash
cd ProjectHandoff/frontend
npm install
npm run dev       # http://localhost:5173, /api proxied to http://localhost:8000
```

Other scripts: `npm run check` (typecheck), `npm run build` (typecheck + production bundle in `dist/`).

---

## Google Drive setup — step by step

Each team connects **its own** Google account at team creation — the creator does this once; members never touch Google anything. Ten minutes, no credit card, no paid tier needed — the free Google account quotas are far beyond what a club team needs.

### Step 1 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with the **team creator's Google account** (the account whose Drive will store the data).
2. In the top bar, open the project picker → **New project** → name it (e.g. `ProjectHandoff`) → **Create**.
3. Make sure that project is selected in the top bar for everything below.

### Step 2 — Enable the Google Drive API

1. Menu → **APIs & Services → Library**.
2. Search for **"Google Drive API"** → open it → **Enable**.

### Step 3 — Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen** → User type: **External** → **Create**.
2. Fill in the required fields: app name (e.g. `ProjectHandoff`), a user support email (yours), and developer contact email (yours). Branding domains are optional.
3. On the **Scopes** step: **Add or remove scopes** → search for and add `https://www.googleapis.com/auth/drive` (the full Drive scope — the backend needs it to verify the team's folder and to grant/revoke member access to it on your behalf).
4. On the **Test users** step: **+ Add users** → add the creator's Google account. While the app is in *Testing*, only these accounts can authorize it — which is exactly what you want.
5. Save.

> **Testing vs Production:** while the consent screen is in *Testing*, Google expires the connection every **7 days** — the creator just clicks **Reconnect Google** on the team page (10 seconds). If you flip the app to *In production*, the connection stops expiring, but Google shows an **"unverified app" warning** before consent (click *Advanced → Go to ProjectHandoff*). Google's verification process is only required once you have 100+ users — a club can happily ignore it and click through the warning, or stay in Testing and re-authorize weekly.

### Step 4 — Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. **Authorized redirect URIs** — add *exactly* the team OAuth callback (the create-team form shows this URI; it must match character-for-character):
   - local development: `http://localhost:8000/api/teams/drive/oauth/callback`
   - production: `https://<your-backend-host>/api/teams/drive/oauth/callback`
4. **Create**, then copy the **Client ID** and **Client secret**.

### Step 5 — Create the team in the app

1. Register in the app and open the **Team** page.
2. Fill the team name/description and paste the **client ID + secret** from Step 4. The form shows you the exact redirect URI to register in Google's console (Step 4.3).
3. **Create team & connect Drive** → you're redirected to Google → sign in with the creator's account and approve (click through the *unverified app* warning if shown).
4. Back on the team page, **Link folder**: paste the link of a Drive folder in the creator's Drive (in Drive: select the folder → *Share → Copy link*, or copy from the browser address bar). The app verifies access through the team's own connection, migrates any staged data into it, and grants every member **writer access** — removing a member revokes it automatically.

That's it. The connection is remembered server-side (gitignored `.tokens/teams/{team_id}/`) — the creator is never asked to authorize again (unless they disconnect or Google expires a Testing-mode token). Everything the team does — tasks, uploads, handovers — flows into that folder, and members just log in and work.

### Legacy single-organizer mode (optional)

One club self-hosting its own copy can skip per-team setup entirely: fill `PH_GOOGLE_CLIENT_ID`/`PH_GOOGLE_CLIENT_SECRET` (or use the `/setup` wizard once), authorize the **organizer's** account on **Settings → Storage & synchronization**, and create the team without Google fields — data then flows through that single organizer account at `http://localhost:8000/api/drive/oauth/callback`. This "host" layout is preserved byte-for-byte for existing deployments.

### Troubleshooting Google setup

| Symptom | Cause & fix |
| --- | --- |
| `redirect_uri_mismatch` at Google login | The redirect URI in Step 4 doesn't exactly match the one shown in the create-team form (scheme, host, port, path). Copy-paste it. |
| **"Google hasn't verified this app"** screen | Normal for an unverified app. Click **Advanced → Go to ProjectHandoff (unsafe)** — it's the team's own app. To avoid the screen, keep the app in Testing and be listed as a test user. |
| **"Access blocked: app tried to access sensitive info"** | Your account isn't a **test user** (Step 3.4), or the app was published without you having authorized it before. Add yourself as a test user. |
| Connection stops working after ~a week | The consent screen is in **Testing** — Google expires refresh tokens after 7 days. Click **Reconnect Google** on the team page, or publish the app (see the note in Step 3). |
| "That Drive folder was not found" when linking | The link is wrong, or the team's connected account can't see the folder. Make sure the folder lives in (or is shared with) the connected account, and paste the full `https://drive.google.com/drive/folders/…` link. |
| Team page says "not connected" suddenly | Google revoked/expired the token (Testing-mode expiry, password change, or manual revoke at myaccount.google.com/permissions). Click **Reconnect Google**. |

---

## Using the app — the guided tour

### Accounts: register, log in, join a team

- **Register** with your name, email and a password (hashed with PBKDF2, 200k iterations — never stored in plain text).
- The **first user** on a fresh deployment creates the team. Everyone else gets in via an **invite link**.
- Invites are generated on the **Team page** by an owner/admin: pick a role and an email, and you get a link valid for **7 days, single-use**. The invitee must register with *that same email address* — this stops link forwarding from sneaking strangers in.
- Have a link? Open it, and the **Join** page walks you through registering (or logging in if the email already has an account).

### Roles — who can do what

| Role | Can do |
| --- | --- |
| **Owner** | Everything admins can, and is the team's anchor account. One per team (the creator). |
| **Admin** | Team settings (name, description, **Drive folder link**), invite/revoke invites, change member roles, remove members, (re)share the Drive folder, connect/disconnect Drive. |
| **Coordinator** | Everything members can, plus **archive projects** and **delete tasks**. |
| **Member** | Create and edit projects, create/claim tasks, work the handover flow, comment, upload attachments, create events — the daily-work roles. |

Admins can adjust any member's role (except nobody can create a second owner), and removed members lose Drive folder access automatically.

### Projects

- **Projects page → New project**: name, description, owner, priority, dates.
- Each project shows **progress** (derived from its tasks), its owner and status.
- Archiving (coordinators and up) tucks a finished project away without deleting its history.

### Tasks

- Open a project → **New task**: title, description, **assignee**, deadline, priority.
- Tasks move through **Not Started → In Progress → Blocked → Under Review → Completed**; the status pill is one click away on the task page.
- Task updates are **version-stamped**: if someone edited the task while you were editing it, you get a clear conflict message instead of silently overwriting their change.
- **Comments** give the task a discussion thread; **attachments** let you pin files (PDFs, images, docs, zips…) straight onto the task.

### Handovers — the whole point

When you can't carry a task anymore (graduating, exams, switching teams):

1. Open the task → **Create handover**.
2. Fill the structured record — this is the knowledge that usually gets lost:
   - **Completed work** — what's done, with context.
   - **Remaining work** — exactly what's left.
   - **Current state** — where things stand right now.
   - **Blockers** — what's stuck and why.
   - **Next actions** — the first moves for the new owner.
   - **Relevant files** — links/pointers to the material that matters.
   - **Notes** — anything else worth knowing.
3. Choose the **proposed owner** — they see it instantly in their **Handovers inbox** (and the dashboard).
4. They decide:
   - **Accept** → the task is reassigned to them (version bumped, so everyone's view stays consistent), and the transfer is auto-commented on the task and logged in the activity feed.
   - **Reject** with a reason → you know it bounced and why.
   - **Request clarification** → you **respond** (updating the record), and they decide again. You can also **cancel** the handover entirely before it's accepted.
5. The **Handovers page** is your inbox/outbox for all of this — nothing gets lost in a DM.

### Events & departments

- Create an **event** (a fair, a competition, an outing) with dates and description.
- Split it into **departments** (logistics, sponsors, tech, publicity…) — each with its own **coordinator**, its own member list, and its own progress.
- The event page rolls up department progress so the lead sees the whole picture at a glance.

### Attachments

- Upload from any task, project or event page. Default limits: **10 MB** per file, extension allow-list (`pdf,doc,docx,xls,xlsx,ppt,pptx,csv,txt,md,png,jpg,jpeg,gif,webp,zip` — configurable).
- Files are stored in the **team's own Drive folder** (under `Files/`, `Projects/{id}/files/`, `Events/{id}/files/`) — so they're right there in Drive, organized, even if you never open this app again.

### Dashboard & activity

- **Dashboard**: your open tasks, handovers waiting on you, upcoming and overdue deadlines, team size, recent activity — the morning coffee screen.
- **Activity**: a complete, reverse-chronological audit trail of the team — every task change, handover step, member join/leave, Drive folder share. Who did what, when. No "wait, who changed this?".

### Settings

- **Profile** — update your display name.
- **Password** — change it (old password required).
- **Appearance** — light/dark theme.
- **Storage & synchronization** — shows the storage mode and Drive connection status; owners/admins can **Authorize** or **Disconnect** Google Drive here, and in local (dev) mode it clearly labels the data as living on this machine.
- **Session** — log out.

### How syncing works (and why it feels fast)

- Your own actions (create, upload, hand over…) **refresh the screen immediately** from the server response.
- A quiet **background poll every 10–15 s** keeps lists fresh while the tab is open (and pauses when the tab is hidden).
- Requests for the screen you're currently on **take priority** over background syncing — page loads and your actions never wait behind a poll.
- Failed syncs **retry themselves** with growing pauses (up to 30 s), so a Wi-Fi blip self-heals without you doing anything.
- The sync indicator (bottom corner) is deliberately quiet: quick traffic shows nothing, a lingering sync shows *Syncing…*, a dragging one warns *Slow connection*, and real failures show the error. Backend reads are cached (per table, short TTL, refreshed instantly by writes), and after a restart the server warms the whole cache in the background — including refreshing its Google credentials — so the first person to open the app never waits for a cold Drive round-trip.

---

## Configuration (`PH_`-prefixed, see `.env.example`)

| Variable | Purpose |
| --- | --- |
| `PH_SECRET_KEY` | HMAC key for auth tokens, invite tokens, OAuth state (required in production) |
| `PH_STORAGE_MODE` | `auto` / `drive` / `local` |
| `PH_ALLOW_LOCAL_STORAGE` | explicit opt-in for local mode |
| `PH_LOCAL_DATA_DIR` | local-mode data directory (default `<ProjectHandoff>/data`) |
| `PH_GOOGLE_CLIENT_ID/SECRET` | Google OAuth client credentials (or enter once in the `/setup` wizard) |
| `PH_GOOGLE_OAUTH_REDIRECT_URI` | must match the Google Cloud console exactly |
| `PH_GOOGLE_TOKEN_FILE` | where the optional host OAuth token is stored (gitignored); team tokens live next to it under `teams/{team_id}/` |
| `PH_DRIVE_ROOT_FOLDER_ID/NAME` | pin an existing Drive folder or auto-create one |
| `PH_MAX_UPLOAD_MB`, `PH_ALLOWED_EXTENSIONS` | upload validation |
| `PH_CORS_ORIGINS`, `PH_FRONTEND_URL` | CORS + OAuth post-callback redirect |
| `PH_BACKUP_RETENTION` | CSV backup files kept per table |
| `PH_TOKEN_TTL_HOURS` | auth token lifetime |

### Deploying for real

Any small server works (the app is one process + Drive doing the heavy lifting): run the backend with uvicorn behind a reverse proxy (nginx/Caddy) on HTTPS, serve the frontend either from `npm run build` output with any static file server, or keep `npm run dev`/`preview` on a private host. Set `PH_FRONTEND_URL` and `PH_CORS_ORIGINS` to the frontend's real URL, and register the backend's `/api/drive/oauth/callback` as the OAuth redirect URI (Step 4 above).

Ready-made setups live in [`deploy/`](deploy/):

- [`deploy/local/`](deploy/local/) — run on your own machine and publish it through a free tunnel (Tailscale Funnel, ngrok, or a Cloudflare Quick Tunnel). No credit card required.
- [`deploy/oracle/`](deploy/oracle/) — Oracle Cloud Always Free VM with Caddy and automatic HTTPS, for an always-on link.

## Tests

```bash
cd ProjectHandoff
backend/.venv/bin/python -m pytest tests -q     # 117 tests
cd frontend && npm run check && npm run build   # typecheck + build
```

The suite covers CSV serialization round-trips, the storage engine (concurrency, backups, corruption recovery, read cache), auth, teams/invitations, projects, tasks/comments, the full handover state machine, events/departments, attachments, dashboard/activity, Google Drive client behaviour (via a fake Drive service), team-owned Drive folders, the setup wizard and the OAuth endpoints.

## Project layout

```
ProjectHandoff/
├── backend/
│   ├── app/
│   │   ├── main.py            # create_app factory, lifespan, exception mapping
│   │   ├── config.py          # PH_-prefixed settings
│   │   ├── security.py        # PBKDF2 hashing, HMAC tokens, invite hashing
│   │   ├── deps.py            # auth dependencies, user cache, role guards
│   │   ├── schemas/           # Pydantic API models
│   │   ├── services/
│   │   │   ├── csvstore.py    # the CSV storage engine (the heart of the app)
│   │   │   ├── activity.py, uploads.py, drive_link.py
│   │   │   └── drive/         # base/local/google_drive backends + factory
│   │   └── routers/           # auth, setup, teams, projects, tasks, handovers,
│   │                          # events, attachments, activity, dashboard, sync
│   ├── tests/                 # 117 pytest tests (fake Drive, no network)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/               # typed client, sync bus, request priority, TS models
│       ├── components/        # UI kit, layout shell, sync indicator
│       ├── hooks/, lib/, state/
│       └── pages/             # 16 screens incl. setup wizard and handover inbox/outbox
├── docs/architecture.md       # how the system fits together
└── scripts/push.sh            # stage/commit/push only ProjectHandoff paths
```

## Data storage layout

All persistent data is CSV text (RFC-4180, UTF-8, header row, ISO-8601 timestamps).

**Global tables** live in the backend root folder (organizer's Drive, or the local data dir in development):

```
<root>/TeamData/
│   users.csv  teams.csv  credentials.csv  invitations.csv  activity.csv
<root>/Backups/global/{table}/…          # rotating backups after every write
```

**Each team that linked a Drive folder at setup owns everything else inside that folder**, shared with all members:

```
<team folder>/AppData/                   # per-team CSV tables (the app's data)
│   projects.csv  events.csv  departments.csv  department_members.csv
│   tasks.csv  handovers.csv  comments.csv  attachments.csv
<team folder>/Files/…                    # team-level uploads
<team folder>/Projects/{project_id}/files/…
<team folder>/Events/{event_id}/files/…
<team folder>/Backups/{table}/…          # rotating per-table backups
```

Teams without a linked folder keep their data under `<root>/TeamData/{team_id}/…` (legacy layout). Writes are serialized per (team, table) with per-scope asyncio locks plus optimistic concurrency (read-revise-write with revision checks, bounded retry) — safe under FastAPI's concurrent request handling. Successful reads are cached briefly; the team's CSVs are backed up (rotating, capped by `PH_BACKUP_RETENTION`) on every write, and a corrupted table is auto-recovered from its newest backup.

## Security notes

- Passwords: PBKDF2-HMAC-SHA256, 200 000 iterations, per-password salt, constant-time comparison.
- Tokens: stateless HMAC-signed claims (user, team, role, exp); 401 responses clear the client token and redirect to login.
- Invitations: stored as SHA-256 hashes; single-use; expire after 7 days; the invitee's email must match the invited address.
- Drive scope: each team authorizes with full `https://www.googleapis.com/auth/drive` scope from its own Google account — required so the backend can read/verify the team's folder (which the creator made manually) and manage sharing permissions on the team's behalf. Team folders are shared per-member (writer) when they join and unshared when they're removed. Team tokens and OAuth clients are stored server-side under `.tokens/teams/{team_id}/` (gitignored) and never logged or exported.
- OAuth state: signed and verified on the callback; the post-login redirect path is validated to be a local path only.
- Uploads: extension allow-list, size cap, filename sanitization, non-guessable storage keys.
- Secrets (`.env`, OAuth tokens, client secrets) are gitignored and never logged.
