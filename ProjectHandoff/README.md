# ProjectHandoff

A production-quality team coordination web app for student clubs — with a **structured task handover** workflow as its headline feature. Built with a React + TypeScript frontend and a FastAPI backend that uses **Google Drive as its only persistent store** (CSV files are the source of truth; uploads live in Drive folders).

> **Why Drive?** The team's data (members, projects, tasks, handovers, events, uploads) lives inside a single organizer's Google Drive. There is no server-side database: every record is a row in a CSV file, every upload is a Drive file, and the organizer owns all of it.

## Features

- **Accounts & teams** — register, log in, create a team, invite members via single-use 7-day invite links (email must match on registration), role management (owner / admin / coordinator / member).
- **Team-owned Drive folders** — at team setup you paste a Google Drive folder link; the app verifies it, stores *all* of the team's files and data tables inside it, and grants every member writer access automatically (revoked when they're removed). No central server-side storage at all.
- **Projects** — list/create/archive projects with owners, priorities and progress.
- **Tasks** — full task lifecycle (Not Started → In Progress → Blocked → Under Review → Completed), assignees, deadlines, priorities, version-stamped updates, comments, attachments.
- **Structured handovers** — the core feature. A task owner hands a task to a teammate by filling a structured handover record: *completed work, remaining work, current state, blockers, next actions, relevant files, notes*. The proposed owner can **accept**, **reject** (with reason), or **request clarification**; the previous owner can **respond** or **cancel**. Every step is logged on the task as comments and in the team activity feed. Acceptance reassigns the task and bumps its version.
- **Events & departments** — events (fairs, competitions) split into departments (logistics, sponsors, tech…) with coordinators, members and per-department progress.
- **Attachments** — upload files to tasks, projects or events (type/size validated, stored in Drive folders).
- **Activity feed** — audit-style, reverse-chronological log of everything happening in the team.
- **Dashboard** — open tasks, pending handovers, upcoming/overdue deadlines, team size, recent activity.
- **Live-sync UX** — data refreshes right after your actions and polls the server every 10–15 s; a sync indicator shows transport health and the last successful sync. Requests for the screen you're on are prioritized over background syncing, and failed syncs retry themselves with backoff.
- **Light/dark theme**, responsive layout, accessible controls.

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Router, lucide-react |
| Backend | Python 3.14, FastAPI, Pydantic / pydantic-settings, google-api-python-client |
| Storage | Google Drive (organizer account) — CSV data tables + upload folders. Explicit local-mode fallback for development. |
| Tests | pytest (backend, 99 tests), `tsc --noEmit` + production Vite build (frontend) |

## Quickstart

### 1. Backend

```bash
cd ProjectHandoff/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # set PH_STORAGE_MODE=drive for production; secrets go in the /setup wizard
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

### 3. First-run setup (no credential files to edit)

With `PH_STORAGE_MODE=drive` and no OAuth client configured, the app opens a **setup wizard at `/setup`**:

1. Create an OAuth client (see "Production with Google Drive" below) — or just have it ready.
2. Paste the **client ID + secret** into the wizard. They're stored server-side in the gitignored `.tokens/` folder (never in Drive, never in the shared data) — no `.env` editing of secrets needed.
3. Click **Connect Google Drive** and approve once with the organizer's Google account.
4. Create your account, then create the team and paste its **Drive folder link** — every member gets access to that folder automatically.

The wizard only appears while the deployment is unconfigured; it locks itself after first run. To rotate credentials, delete `.tokens/oauth_client.json` and restart.

### 4. Production with Google Drive

1. Create a Google Cloud project, enable the **Drive API**, and create an OAuth 2.0 *Web application* client.
2. Add `http://<your-backend-host>/api/drive/oauth/callback` as an authorized redirect URI.
3. Fill in `PH_GOOGLE_CLIENT_ID`, `PH_GOOGLE_CLIENT_SECRET`, `PH_GOOGLE_OAUTH_REDIRECT_URI` in `.env`, set `PH_STORAGE_MODE=drive` and a strong `PH_SECRET_KEY`.
4. The team organizer opens **Settings → Authorize Google Drive** once; the backend stores the token (gitignored path) and *all* team data then flows through that single organizer account.

## Configuration (`PH_`-prefixed, see `.env.example`)

| Variable | Purpose |
| --- | --- |
| `PH_SECRET_KEY` | HMAC key for auth tokens, invite tokens, OAuth state (required in production) |
| `PH_STORAGE_MODE` | `auto` / `drive` / `local` |
| `PH_ALLOW_LOCAL_STORAGE` | explicit opt-in for local mode |
| `PH_LOCAL_DATA_DIR` | local-mode data directory (default `<ProjectHandoff>/data`) |
| `PH_GOOGLE_CLIENT_ID/SECRET` | Google OAuth client credentials |
| `PH_GOOGLE_OAUTH_REDIRECT_URI` | must match the Google Cloud console exactly |
| `PH_GOOGLE_TOKEN_FILE` | where the organizer OAuth token is stored (gitignored) |
| `PH_DRIVE_ROOT_FOLDER_ID/NAME` | pin an existing Drive folder or auto-create one |
| `PH_MAX_UPLOAD_MB`, `PH_ALLOWED_EXTENSIONS` | upload validation |
| `PH_CORS_ORIGINS`, `PH_FRONTEND_URL` | CORS + OAuth post-callback redirect |
| `PH_BACKUP_RETENTION` | CSV backup files kept per table |
| `PH_TOKEN_TTL_HOURS` | auth token lifetime |

## Tests

```bash
cd ProjectHandoff
backend/.venv/bin/python -m pytest tests -q     # 99 tests
cd frontend && npm run check && npm run build   # typecheck + build
```

The suite covers CSV serialization round-trips, the storage engine (concurrency, backups, corruption recovery), auth, teams/invitations, projects, tasks/comments, the full handover state machine, events/departments, attachments, dashboard/activity, Google Drive client behaviour (via a fake Drive service) and the OAuth endpoints.

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
│   │   │   ├── activity.py, uploads.py
│   │   │   └── drive/         # base/local/google_drive backends + factory
│   │   └── routers/           # auth, teams, projects, tasks, handovers,
│   │                          # events, attachments, activity, dashboard, sync
│   ├── tests/                 # 99 pytest tests (fake Drive, no network)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/               # typed client, sync bus, TS models
│       ├── components/        # UI kit, layout shell, sync indicator
│       ├── hooks/, lib/, state/
│       └── pages/             # 13 screens incl. handover inbox/outbox
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

Teams without a linked folder keep their data under `<root>/TeamData/{team_id}/…` (legacy layout). Writes are serialized per (team, table) with per-scope asyncio locks plus optimistic concurrency (read-revise-write with revision checks, bounded retry) — safe under FastAPI's concurrent request handling.

## Security notes

- Passwords: PBKDF2-HMAC-SHA256, 200 000 iterations, per-password salt, constant-time comparison.
- Tokens: stateless HMAC-signed claims (user, team, role, exp); 401 responses clear the client token and redirect to login.
- Invitations: stored as SHA-256 hashes; single-use; expire after 7 days; the invitee's email must match the invited address.
- Drive scope: the organizer authorizes with full `https://www.googleapis.com/auth/drive` scope — required so the backend can read/verify team folders the organizer created manually and manage sharing permissions on the team's behalf. Team folders are shared per-member (writer) when they join and unshared when they're removed.
- Uploads: extension allow-list, size cap, filename sanitization, non-guessable storage keys.
- Secrets (`.env`, OAuth tokens, client secrets) are gitignored and never logged.
