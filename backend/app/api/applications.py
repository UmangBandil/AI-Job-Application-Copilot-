"""Application tracker API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Application, JobDescription, User
from app.schemas.schemas import ApplicationCreate, ApplicationResponse, ApplicationUpdate

router = APIRouter(prefix="/applications", tags=["applications"])


def _app_response(app: Application, jd: JobDescription | None = None) -> ApplicationResponse:
    return ApplicationResponse(
        id=app.id,
        job_description_id=app.job_description_id,
        resume_id=app.resume_id,
        status=app.status,
        match_score=app.match_score,
        cover_letter=app.cover_letter or "",
        tailored_resume=app.tailored_resume or "",
        notes=app.notes or "",
        follow_up_date=app.follow_up_date,
        created_at=app.created_at,
        updated_at=app.updated_at,
        job_title=jd.title if jd else "",
        company=jd.company if jd else "",
    )


@router.post("", response_model=ApplicationResponse, status_code=201)
async def create_application(
    payload: ApplicationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new application entry."""
    # Verify JD
    jd_result = await db.execute(
        select(JobDescription).where(
            JobDescription.id == payload.job_description_id,
            JobDescription.user_id == user.id,
        )
    )
    jd = jd_result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    app = Application(
        user_id=user.id,
        job_description_id=payload.job_description_id,
        resume_id=payload.resume_id,
        match_score=payload.match_score,
        cover_letter=payload.cover_letter,
        tailored_resume=payload.tailored_resume,
        notes=payload.notes,
    )
    db.add(app)
    await db.flush()
    await db.refresh(app)

    return _app_response(app, jd)


@router.get("", response_model=list[ApplicationResponse])
async def list_applications(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all applications, optionally filtered by status."""
    query = select(Application).where(Application.user_id == user.id)
    if status:
        query = query.where(Application.status == status)
    query = query.order_by(Application.updated_at.desc())

    result = await db.execute(query)
    applications = result.scalars().all()

    response = []
    for app in applications:
        jd_result = await db.execute(
            select(JobDescription).where(JobDescription.id == app.job_description_id)
        )
        jd = jd_result.scalar_one_or_none()
        response.append(_app_response(app, jd))

    return response


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific application."""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == app.job_description_id)
    )
    jd = jd_result.scalar_one_or_none()

    return _app_response(app, jd)


@router.patch("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: str,
    payload: ApplicationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an application (status, notes, follow-up date, etc.)."""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(app, field, value)

    await db.flush()
    await db.refresh(app)

    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == app.job_description_id)
    )
    jd = jd_result.scalar_one_or_none()

    return _app_response(app, jd)


@router.delete("/{app_id}", status_code=204)
async def delete_application(
    app_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an application."""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user.id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    await db.delete(app)
