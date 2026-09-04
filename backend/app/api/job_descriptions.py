"""Job Description ingestion and management API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import JobDescription, Resume, User
from app.schemas.schemas import JDCreate, JDResponse, MatchRequest, MatchScoreResponse
from app.services.jd_service import parse_jd, fetch_jd_from_url
from app.services.matching_service import compute_match_score
from app.models import MatchScore

router = APIRouter(prefix="/job-descriptions", tags=["job-descriptions"])


@router.post("", response_model=JDResponse, status_code=201)
async def create_jd(
    payload: JDCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a job description from pasted text or URL."""
    raw_text = payload.raw_text

    # If URL provided, fetch the content
    if payload.source_url and not raw_text.strip():
        try:
            raw_text = await fetch_jd_from_url(payload.source_url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch JD from URL: {str(e)}")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="No job description text provided")

    # Parse the JD
    parsed_data = parse_jd(raw_text)

    # Use extracted role as title if none provided
    title = payload.title or parsed_data.get("role", "") or "Untitled Position"

    jd = JobDescription(
        user_id=user.id,
        title=title,
        company=payload.company,
        raw_text=raw_text,
        source_url=payload.source_url,
        parsed_data=parsed_data,
    )
    db.add(jd)
    await db.flush()
    await db.refresh(jd)

    return JDResponse.model_validate(jd)


@router.post("/from-url", response_model=JDResponse, status_code=201)
async def create_jd_from_url(
    url: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a job description by fetching and parsing a URL."""
    try:
        raw_text = await fetch_jd_from_url(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch JD from URL: {str(e)}")

    parsed_data = parse_jd(raw_text)
    title = parsed_data.get("role", "") or "Untitled Position"

    jd = JobDescription(
        user_id=user.id,
        title=title,
        raw_text=raw_text,
        source_url=url,
        parsed_data=parsed_data,
    )
    db.add(jd)
    await db.flush()
    await db.refresh(jd)

    return JDResponse.model_validate(jd)


@router.get("", response_model=list[JDResponse])
async def list_jds(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all job descriptions."""
    result = await db.execute(
        select(JobDescription).where(JobDescription.user_id == user.id).order_by(JobDescription.created_at.desc())
    )
    return [JDResponse.model_validate(jd) for jd in result.scalars().all()]


@router.get("/{jd_id}", response_model=JDResponse)
async def get_jd(
    jd_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific job description."""
    result = await db.execute(
        select(JobDescription).where(JobDescription.id == jd_id, JobDescription.user_id == user.id)
    )
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")
    return JDResponse.model_validate(jd)


@router.delete("/{jd_id}", status_code=204)
async def delete_jd(
    jd_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a job description."""
    result = await db.execute(
        select(JobDescription).where(JobDescription.id == jd_id, JobDescription.user_id == user.id)
    )
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")
    await db.delete(jd)


@router.post("/match", response_model=MatchScoreResponse, status_code=201)
async def match_jd_to_resume(
    payload: MatchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute match score between a resume and a job description."""
    # Verify JD ownership
    jd_result = await db.execute(
        select(JobDescription).where(
            JobDescription.id == payload.job_description_id,
            JobDescription.user_id == user.id,
        )
    )
    if not jd_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job description not found")

    # Verify resume ownership
    resume_result = await db.execute(
        select(Resume).where(
            Resume.id == payload.resume_id,
            Resume.user_id == user.id,
        )
    )
    if not resume_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume not found")

    try:
        scores = await compute_match_score(
            db, str(payload.resume_id), str(payload.job_description_id)
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    match_record = MatchScore(
        user_id=user.id,
        job_description_id=payload.job_description_id,
        resume_id=payload.resume_id,
        overall_score=scores["overall_score"],
        matched_skills=scores["matched_skills"],
        missing_skills=scores["missing_skills"],
        suggested_bullets=scores["suggested_bullets"],
    )
    db.add(match_record)
    await db.flush()
    await db.refresh(match_record)

    return MatchScoreResponse.model_validate(match_record)
