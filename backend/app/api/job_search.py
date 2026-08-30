"""Job search API routes — external job board integration."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import JobSearchResult, User
from app.schemas.schemas import JobSearchParams, JobSearchResultResponse
from app.services.job_search_service import search_jobs

settings = get_settings()
router = APIRouter(prefix="/job-search", tags=["job-search"])


@router.post("", response_model=list[JobSearchResultResponse])
async def search(
    payload: JobSearchParams,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search external job boards and save results."""
    results = await search_jobs(
        query=payload.query,
        location=payload.location,
        page=payload.page,
        source=payload.source,
        adzuna_app_id=settings.ADZUNA_APP_ID,
        adzuna_app_key=settings.ADZUNA_APP_KEY,
    )

    saved = []
    for r in results:
        record = JobSearchResult(
            user_id=user.id,
            title=r["title"],
            company=r.get("company", ""),
            location=r.get("location", ""),
            description=r.get("description", ""),
            url=r.get("url", ""),
            source=r.get("source", "unknown"),
            salary_min=r.get("salary_min"),
            salary_max=r.get("salary_max"),
            raw_data=r.get("raw_data", {}),
        )
        db.add(record)
        saved.append(record)

    await db.flush()

    return [
        JobSearchResultResponse.model_validate(r) for r in saved
    ]


@router.post("/{result_id}/import", status_code=201)
async def import_search_result(
    result_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import a search result into the Job Descriptions table."""
    from app.models import JobDescription
    from app.services.jd_service import parse_jd

    result = await db.execute(
        select(JobSearchResult).where(
            JobSearchResult.id == result_id,
            JobSearchResult.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Search result not found")

    parsed_data = parse_jd(record.description or record.title)

    jd = JobDescription(
        user_id=user.id,
        title=record.title,
        company=record.company,
        raw_text=record.description,
        source_url=record.url,
        parsed_data=parsed_data,
    )
    db.add(jd)
    record.imported = True
    await db.flush()
    await db.refresh(jd)

    return {"id": str(jd.id), "title": jd.title, "message": "Imported successfully"}


@router.get("/saved", response_model=list[JobSearchResultResponse])
async def list_saved_results(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List previously saved search results."""
    result = await db.execute(
        select(JobSearchResult)
        .where(JobSearchResult.user_id == user.id)
        .order_by(JobSearchResult.created_at.desc())
        .limit(100)
    )
    return [JobSearchResultResponse.model_validate(r) for r in result.scalars().all()]
