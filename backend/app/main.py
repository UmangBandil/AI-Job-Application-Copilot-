"""AI Job Application Copilot — FastAPI backend."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.database import init_db

settings = get_settings()

# Path to built frontend (set in production Dockerfile)
_static_dir_raw = os.environ.get("STATIC_FILES_DIR", "")
STATIC_DIR = Path(_static_dir_raw) if _static_dir_raw else Path("")
IS_PRODUCTION = STATIC_DIR.is_absolute() and STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup."""
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
origins = list(settings.CORS_ORIGINS)
if IS_PRODUCTION:
    origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# All API routes under /api/v1
api_router = APIRouter(prefix="/api/v1")

from app.api.auth import router as auth_router
from app.api.resumes import router as resumes_router
from app.api.job_descriptions import router as jd_router
from app.api.generation import router as generation_router
from app.api.applications import router as applications_router
from app.api.job_search import router as job_search_router
from app.api.dashboard import router as dashboard_router

api_router.include_router(auth_router)
api_router.include_router(resumes_router)
api_router.include_router(jd_router)
api_router.include_router(generation_router)
api_router.include_router(applications_router)
api_router.include_router(job_search_router)
api_router.include_router(dashboard_router)

app.include_router(api_router)


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "service": settings.APP_NAME}


# ── Serve frontend in production ──────────────────────────────────────
if IS_PRODUCTION:
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(STATIC_DIR / "index.html"))
