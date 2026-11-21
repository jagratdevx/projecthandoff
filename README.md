# ProjectHandoff

Team coordination for student clubs, built around structured task handovers.
ProjectHandoff pairs a React + TypeScript frontend with a FastAPI backend that
uses Google Drive as its only persistent store — CSV files are the source of
truth and uploads live in the team's own Drive folders.

## Repository layout

- `ProjectHandoff/backend` — FastAPI API, auth, workflow and Drive CSV storage
- `ProjectHandoff/frontend` — React + Vite UI
- `ProjectHandoff/tests` — pytest suite
- `ProjectHandoff/README.md` — setup, Google Drive configuration and usage guide

## Quick start

See [`ProjectHandoff/README.md`](ProjectHandoff/README.md) for prerequisites,
Google Drive setup, running the backend and frontend, and the full user guide.
