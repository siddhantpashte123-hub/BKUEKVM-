"""BLUEKVM PANNEL — FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .deps import CSRF_COOKIE, CSRF_HEADER, SAFE_METHODS
from .security import constant_time_equals
from .virtualization.base import HypervisorError

from . import __version__
from .api import (
    auth,
    backups,
    dashboard,
    health,
    logs,
    monitoring,
    nodes,
    settings as settings_api,
    storage,
    templates,
    vps,
    users,
    networks,
)
from .bootstrap import run_bootstrap
from .config import settings
from .console.ws import router as console_router
from .console.ssh_ws import router as ssh_router
from .database import Base, SessionLocal, engine
from .logging_config import configure_logging
from .services.worker import embedded_worker

configure_logging()
log = logging.getLogger("bluekvm.main")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # In production Alembic owns migrations; create_all is a safe fallback for
    # fresh SQLite dev databases and is a no-op for existing tables.
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        do_health_check = (
            settings.is_dev and os.getenv("BLUEKVM_STARTUP_HEALTHCHECK", "1") == "1"
        )
        result = run_bootstrap(db, health_check=do_health_check)
        if result.get("generated_admin_password"):
            log.info("Generated admin password (also printed above on first run)")
    finally:
        db.close()

    stop_event = asyncio.Event()
    worker_task = None
    if os.getenv("BLUEKVM_EMBEDDED_WORKER", "1") == "1":
        worker_task = asyncio.create_task(embedded_worker(stop_event))
    log.info("BLUEKVM PANNEL %s started on %s:%s (env=%s)", __version__, settings.host, settings.port, settings.env)
    yield
    stop_event.set()
    if worker_task:
        worker_task.cancel()


app = FastAPI(
    title="BLUEKVM PANNEL API",
    version=__version__,
    description="Self-hosted KVM VPS management platform",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

# Same-origin deployment: do not add wildcard CORS. Cookies are SameSite=Lax.
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Stateless double-submit CSRF check covering EVERY mutating route."""
    exempt_paths = {"/api/auth/login"}  # no cookie exists before authentication
    if (
        settings.csrf_enabled
        and not settings.is_dev
        and request.method not in SAFE_METHODS
        and request.url.path not in exempt_paths
        and not request.url.path.startswith("/health")
    ):
        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        header_token = request.headers.get(CSRF_HEADER, "")
        if not cookie_token or not header_token or not constant_time_equals(cookie_token, header_token):
            return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
    return await call_next(request)


for module in (
    health, auth, dashboard, vps, nodes, templates, networks, storage,
    backups, users, logs, monitoring, settings_api,
):
    app.include_router(module.router)
app.include_router(console_router)
app.include_router(ssh_router)


@app.exception_handler(HypervisorError)
async def hypervisor_error_handler(request: Request, exc: HypervisorError):
    # KVM unavailable / placement failures are client-visible conflicts, not 500s
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check server logs for details."},
    )


# ------------------------------------------------------------ SPA hosting --
if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def root_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "ws/", "health/")):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        target = FRONTEND_DIST / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def api_only_notice():
        return {
            "name": "BLUEKVM PANNEL API",
            "version": __version__,
            "docs": "/api/docs",
            "notice": "Frontend build not found. Build frontend/ or run via the dev proxy.",
        }
