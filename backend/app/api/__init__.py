from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")


def register_routers():
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


register_routers()
