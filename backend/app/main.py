"""AI Job Application Copilot — FastAPI backend."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db

settings = get_settings()


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
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
