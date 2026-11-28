# ProjectHandoff — Architecture

## 1. High-level picture

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Browser (React 18 + TypeScript, Vite build)                               │
│    pages/ 13 screens · api/client.ts (fetch + token + sync bus)            │
│    state/AuthContext · state/ToastContext · hooks/useResource (polling)    │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ HTTPS, JSON, bearer token
                               │ (vite dev proxy → :8000 in development)
┌──────────────────────────────▼─────────────────────────────────────────────┐
│  FastAPI backend (Python 3.14)                                             │
│    routers/ (auth, teams, projects, tasks, handovers, events,               │
│              attachments, activity, dashboard, sync)                        │
│    deps.py  — auth (HMAC token → user), require_team, require_roles         │
│    schemas/ — Pydantic request/response models                              │
├────────────────────────────────────────────────────────────────────────────┤
│  services/csvstore.py  — THE storage engine (only state boundary)           │
│    per-scope asyncio locks · optimistic concurrency · rotating backups      │
├────────────────────────────────────────────────────────────────────────────┤
│  services/drive/       — one of two backends, chosen at startup             │
│    GoogleDriveBackend  (googleapiclient, organizer OAuth token)             │
│    LocalDriveBackend   (filesystem mirror, dev-only, explicit opt-in)       │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               ▼
                    Google Drive folder (organizer account)
                    CSV tables (source of truth) + upload files + backups
```

Single FastAPI process, no database server. **Every persistent byte lives in the
Drive backend** — CSV tables for structured data, regular files for uploads.

## 2. The CSV storage engine (`services/csvstore.py`)

### Tables & scopes

Two scopes:

- **Global** — `users.csv`, `teams.csv`, `credentials.csv` (password hashes),
  `invitations.csv`, `activity.csv`, `team_memberships.csv` → `TeamData/`
- **Team** — `projects`, `events`, `departments`, `department_members`, `subteams`,
  `subteam_members`, `subteam_activity`, `activity_log`, `tasks`, `handovers`,
  `comments`, `attachments` → `TeamData/{team_id}/`

Beyond the product spec, two pragmatic additions: `credentials.csv`
(auth decoupled from the public `users` table) and `department_members.csv`
(many-to-many between departments and users; composite key, no id column —
explicitly excluded from id validation). Subteams are a team-scoped CSV table
with a case-insensitive unique name; each one also gets a readable Drive folder
at `Subteams/{name}/` inside the team folder. Projects append `subteam_id` and
`requirements`; tasks derive their scope from the project and restrict assignees
to active `subteam_members`. Uploads keep the existing `Projects/{project_id}/files`
Drive path so no folders are orphaned.

`team_memberships.csv` is authoritative for per-team role and state
(`active`/`observer`/`removed`); `users.team_id/role` are mirrors of the current
context so existing single-team endpoints keep working. `activity_log.csv` mirrors
main and subteam activity entries with a `source` column and is never trimmed by
the global activity cap. Completing a team flips `teams.status` to `archived`;
`CsvStore.mutate` then rejects team-scoped writes, Drive grants become reader-only,
and the archive APIs read `activity_log.csv` for durable memories.

### Serialization & correctness

FastAPI handles requests concurrently, so the engine enforces correctness with:

1. **Per-(team, table) asyncio locks** — inserts/mutations never interleave for
   the same table.
2. **Optimistic concurrency** — every write is read-modify-write under the
   lock: re-read the file, verify it still matches the revision seen when the
   caller loaded rows, write atomically (tmp file + replace semantics through
   the backend), keeping a version counter. Conflicts (a write between our read
   and write) raise `StaleRevision`.
3. **Bounded retry** — `StaleRevision` and transient Drive errors are retried
   up to 4 times; auth failures propagate immediately (retrying cannot help).
4. **Backups** — after *every* successful write, the previous revision is
   copied to `Backups/{scope}/{table}/{timestamp}-{table}.csv`, retention
   capped (`PH_BACKUP_RETENTION`, default 20, newest kept).
5. **Corruption recovery** — on parse failure the engine transparently tries
   backups newest-first and restores the newest parseable one, then logs
   loudly. A corrupt empty file (truncated upload, interrupted transfer) is a
   *recoverable* state, not data loss.
6. **Typed rows** — values cross the boundary as strict strings; CSV round-trip
   is exercised by dedicated serialization tests (newlines, quotes, unicode).

### Atomicity boundaries

A logical operation (e.g. "accept handover") spans multiple tables
(handovers + tasks + comments + activity). Each table write is individually
atomic and backed up; the sequencing (handover → task → comment → activity)
is ordered so a crash between steps leaves a consistent, discoverable state
(the handover row is the entry point for any reconciliation).

## 3. Drive backends (`services/drive/`)

`DriveBackend` is the abstract interface: `read_file`, `write_file`,
`append_row`-friendly reads, `upload_file`, `download_file`, `delete_file`,
`list_folder`, `ensure_folder`, `file_exists` — plus typed exceptions
(`DriveAuthError`, `DriveTransientError`, `StaleRevision`, `NotFoundError`).

- **GoogleDriveBackend** — talks to Drive v3 via the organizer's OAuth token.
  Folder hierarchy mirrors the data layout (below). Uploads are resumable
  media uploads; content revisions are guarded by optimistic checks on file
  content revisions.
- **LocalDriveBackend** — filesystem mirror with the identical API used for
  development and for the test-suite's `FakeDriveService`. It exists so the
  whole engine is exercisable without network/credentials.

### Mode selection (`drive/factory.py`) — no silent fallback

| `PH_STORAGE_MODE` | Behaviour |
| --- | --- |
| `auto` | Use Drive if a valid OAuth token exists; otherwise **fail startup** with precise setup instructions. |
| `drive` | Require Drive outright. |
| `local` | Local filesystem **only** with explicit `PH_ALLOW_LOCAL_STORAGE=true`; startup logs a prominent warning that data is not on Drive. |

Silent degradation is treated as a bug: a misconfiguration must stop the
startup, never quietly pick a different storage root.

### Drive layout

```
ProjectHandoff/                     (root folder id or auto-created name)
├── TeamData/
│   ├── users.csv … activity.csv    (global tables)
│   └── {team_id}/
│       ├── projects.csv … attachments.csv
│       └── files/{attachment_id}/{file_name}
├── Projects/{team_id}/{project_id}/files/{attachment_id}/{file_name}
├── Events/{team_id}/{event_id}/files/{attachment_id}/{file_name}
└── Backups/{scope}/{table}/{ts}-{table}.csv
```

Uploads live in per-attachment folders keyed by a UUID, so file names can be
human-friendly without collisions.

## 4. Authentication & authorization

- **Registration/login**: email + password. PBKDF2-HMAC-SHA256 (200 000
  iterations, per-salt) hashes stored in `credentials.csv`, keyed by `user_id`
  (email changes don't orphan hashes; duplicate emails rejected).
- **Tokens**: stateless, HMAC-signed claim set `{sub, team, role, iat, exp}`
  (`PH_SECRET_KEY`, default TTL 168 h). No session table: every request
  re-derives identity from the signed token plus a 5-second in-memory user
  cache (invalidated by any users-table write via `invalidate_user_cache`).
- **Team roles**: `owner` (creator) > `admin` > `coordinator` > `member`.
  Route guards `require_team` (must belong to a team) and `require_roles`.
- **Invitations**: single-use, 7-day expiry, email-bound (invitee must
  register with exactly the invited address), stored as SHA-256 hash with a
  shareable URL `…/join?token=…`.

## 5. The handover state machine (headline feature)

```
                     propose (assignee or admin)
  ┌──────────────────────────────────────────────────────────┐
  │                                                          ▼
  │                                                     ┌────────┐
  │            previous owner cancels                   │pending │
  │        ┌────────────────────────────────────────────┴───┬────┘
  │        │                                                │
  ▼        │ proposed owner accepts           proposed owner│   proposed owner
┌────────┐ │                                  requests info│   rejects (reason)
│cancelled│ │                                               ▼      ▼
└────────┘ │                                        ┌──────────────────┐
           │                                        │clarification_req.│──┐
           │                                        └────────┬─────────┘  │
           │                previous owner responds (→ pending)│            │
           │                       previous owner responds     │            │
           │                              (from cancelled/     │            │
           │                               rejected → pending) │            │
           └───────────────────────────────────────────────────┴────────────┘
```

Rules enforced server-side:

- Only the **current assignee** (or an admin) may propose; only the
  **proposed owner** may accept / reject / request clarification.
- `accept` valid only from `pending`; `respond` valid from
  `clarification_requested`, `cancelled` or `rejected` (back to `pending`).
- One open handover per task (`pending`/`clarification_requested`).
- Every action posts a human-readable comment on the task and an activity log
  entry — the structured record is never hidden in an admin screen.
- `accept` reassigns the task, bumps `version`, stamps `accepted_at`.
- Handover history and the structured record stay queryable from the task
  detail page.

## 6. Frontend architecture

- **API layer** (`api/client.ts`): thin `fetch` wrapper with token injection,
  typed `ApiError`, 401 → token clear + redirect, and a **sync bus** — a tiny
  event emitter tracking inflight count, transport errors and
  `lastSyncedAt`.
- **Sync indicator** (top bar) subscribes to the sync bus: green (last sync
  time), amber pulse (requests inflight), red (transport error). Data refresh
  happens after every mutating action (explicit `reload()`) plus 10–15 s
  background polling (`useResource`), paused while the tab is hidden.
- **State**: no global data store; `AuthContext` holds the session, pages own
  their data via `useResource`. Toasts via `ToastContext`.
- **Design system**: Tailwind with a small component kit (`components/ui.tsx`)
  — buttons, fields, modals, badges, progress bars, skeletons — plus a class
  strategy dark mode (`ph_theme` in localStorage, OS default first).
- **Routing**: React Router; `AuthGate` for `/login /register /join`
  (redirect signed-in users), `ProtectedLayout` guards the app shell
  (`Layout` renders `<Outlet/>`) around 10 authenticated routes.

## 7. Testing strategy

- **Backend (99 pytest tests)**: CSV serialization round-trips; storage engine
  behaviour (locks, revision conflicts, retries, backups, corruption
  recovery); the full API surface through FastAPI's TestClient; Drive client
  behaviour against a fake Drive service (real `HttpError` semantics, arming
  flaky/auth-failure faults); OAuth flow logic. No network, no credentials.
- **Frontend**: `tsc --noEmit` under strict flags + production Vite build as
  the CI-style gate.
- **E2E smoke**: a local-mode backend exercised with real curl flows
  (register → team → project → task → handover → accept → comments →
  attachments → events → departments), verified against the resulting CSVs.

## 8. Failure & recovery posture

| Failure | Outcome |
| --- | --- |
| Drive 5xx / transient network | bounded retry in the engine; sync indicator flags transport errors in the UI |
| OAuth token revoked | `DriveAuthError` → surfaced; organizer re-authorizes from Settings; no silent fallback |
| CSV corrupted (bad write/transfer) | automatic restore from newest parseable backup |
| Two writers race | optimistic revision check + bounded retry; never lost-update-by-default |
| Accidental deletion | rotating backups retain the last 20 revisions per table |
