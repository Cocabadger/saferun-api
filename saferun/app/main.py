from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .routers.archive import router as archive_router
from .routers.github import router as github_router
from .routers.notion import router as notion_router
from .routers.health import router as health_router
from .routers.metrics import router as metrics_router
from .routers.git_operations import router as git_router
from .routers.auth import router as auth_router
from .routers.approvals import router as approvals_router
from .routers.slack import router as slack_router
from .routers.settings import router as settings_router
from saferun import __version__ as SR_VERSION
from . import storage as storage_manager
from . import db_adapter as db

DATABASE_URL = os.getenv("DATABASE_URL")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # on startup

    # Ensure data directory exists for SQLite
    if not DATABASE_URL or not DATABASE_URL.startswith("postgres"):
        storage_backend = os.getenv("SR_STORAGE_BACKEND", "sqlite").lower()
        if storage_backend == "sqlite":
            sqlite_path = os.getenv("SR_SQLITE_PATH", "/data/saferun.db")
            sqlite_dir = os.path.dirname(sqlite_path)
            if sqlite_dir and not os.path.exists(sqlite_dir):
                os.makedirs(sqlite_dir, exist_ok=True)

    db.init_db()
    storage = storage_manager.get_storage()
    storage.run_gc()
    yield
    # on shutdown (if needed)

app = FastAPI(title="SafeRun", version=SR_VERSION, lifespan=lifespan)

# Configure CORS
allowed_origins = os.getenv("SR_ALLOWED_ORIGINS", "*")
if allowed_origins == "*":
    origins = ["*"]
else:
    origins = [origin.strip() for origin in allowed_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": "SafeRun API",
        "version": SR_VERSION,
        "description": "AI Safety Middleware - Prevent destructive actions",
        "docs": "https://github.com/Cocabadger/saferun-api",
        "endpoints": {
            "health": "/readyz",
            "register": "POST /v1/auth/register",
            "dry_run": "POST /v1/dry-run/{provider}.{action}",
        },
    }


@app.get("/v1/health/notion")
def health_notion():
    return {"status": "ok", "service": "saferun", "version": SR_VERSION}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        410: "GONE",
        502: "BAD_GATEWAY",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error_code": code_map.get(exc.status_code, "HTTP_ERROR"),
            "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
            "service": "saferun",
            "version": SR_VERSION,
        },
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # Let FastAPI/Starlette handle HTTPException and friends separately
    from fastapi import HTTPException as _HTTPException
    if isinstance(exc, _HTTPException):
        # unified error envelope
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error_code": getattr(exc, "detail", "HTTP_ERROR"),
                "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
                "service": "saferun",
                "version": SR_VERSION,
            },
        )
    # unexpected exceptions
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": str(exc),
            "service": "saferun",
            "version": SR_VERSION,
        },
    )

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(auth_router)  # Auth doesn't require API key
app.include_router(approvals_router)  # Approvals for web dashboard
app.include_router(slack_router)  # Slack notifications (not a provider)
app.include_router(settings_router)  # User settings

# MVP: GitHub-only provider
app.include_router(github_router)
app.include_router(archive_router)
app.include_router(git_router)

# Other providers - Coming after MVP testing
# app.include_router(notion_router)
