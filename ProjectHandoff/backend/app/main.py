from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings
from app.routers import (
    activity as activity_router,
    attachments as attachments_router,
    auth as auth_router,
    dashboard as dashboard_router,
    sync as sync_router,
    events as events_router,
    handovers as handovers_router,
    projects as projects_router,
    tasks as tasks_router,
    teams as teams_router,
)
from app.services.csvstore import (
    ConflictError,
    CsvStore,
    NotFoundError,
    StoreError,
    ValidationError,
    now_iso,
)
from app.services.drive.base import DriveAuthError, DriveError, DriveTransientError
from app.services.drive.factory import create_drive_backend

logger = logging.getLogger("projecthandoff")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def create_app(settings: Settings | None = None, backend=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await app.state.db.init()
            logger.info("Storage initialized (mode=%s)", app.state.backend.mode)
            if app.state.backend.mode == "local":
                logger.warning(
                    "*** LOCAL DEVELOPMENT MODE *** Data is stored in plain files on this "
                    "machine, NOT in Google Drive. Set PH_STORAGE_MODE=drive and complete "
                    "OAuth for production use."
                )
        except Exception as exc:  # app still starts; endpoints report 5xx
            logger.error("Storage initialization failed: %s", exc)
        yield

    app = FastAPI(
        title="ProjectHandoff API",
        description="Team coordination with structured responsibility handovers. "
        "Google Drive CSV files are the single source of truth.",
        version="1.0.0",
        lifespan=lifespan,
    )

    if backend is None:
        backend = create_drive_backend(settings)
    db = CsvStore(backend, backup_retention=settings.backup_retention)
    app.state.settings = settings
    app.state.backend = backend
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    # Consistent error responses                                          #
    # ------------------------------------------------------------------ #

    @app.exception_handler(NotFoundError)
    async def _not_found(_req: Request, exc: NotFoundError) -> JSONResponse:
        return _error(404, str(exc))

    @app.exception_handler(ConflictError)
    async def _conflict(_req: Request, exc: ConflictError) -> JSONResponse:
        return _error(409, str(exc))

    @app.exception_handler(ValidationError)
    async def _invalid(_req: Request, exc: ValidationError) -> JSONResponse:
        return _error(400, str(exc))

    @app.exception_handler(StoreError)
    async def _store(_req: Request, exc: StoreError) -> JSONResponse:
        return _error(500, f"Storage error: {exc}")

    @app.exception_handler(DriveAuthError)
    async def _drive_auth(_req: Request, exc: DriveAuthError) -> JSONResponse:
        return _error(503, str(exc))

    @app.exception_handler(DriveTransientError)
    async def _drive_transient(_req: Request, exc: DriveTransientError) -> JSONResponse:
        return _error(503, str(exc))

    @app.exception_handler(DriveError)
    async def _drive(_req: Request, exc: DriveError) -> JSONResponse:
        return _error(502, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(p) for p in first.get("loc", [])[1:]) or "body"
        return JSONResponse(
            status_code=422,
            content={"detail": f"Invalid {location}: {first.get('msg', 'validation failed')}"},
        )

    # ------------------------------------------------------------------ #
    # Routers                                                             #
    # ------------------------------------------------------------------ #

    app.include_router(auth_router.router)
    app.include_router(teams_router.router)
    app.include_router(teams_router.invitations_router)
    app.include_router(projects_router.router)
    app.include_router(tasks_router.router)
    app.include_router(tasks_router.comments_router)
    app.include_router(handovers_router.router)
    app.include_router(events_router.router)
    app.include_router(events_router.departments_router)
    app.include_router(attachments_router.router)
    app.include_router(activity_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(sync_router.router)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "storage_mode": app.state.backend.mode, "time": now_iso()}

    return app


app = create_app()
