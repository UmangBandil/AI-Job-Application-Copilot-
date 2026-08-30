"""RAG-grounded content generation API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import JobDescription, Resume, User
from app.schemas.schemas import GenerateRequest, GeneratedContent
from app.services.generation_service import generate_content

router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("", response_model=GeneratedContent)
async def generate(
    payload: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate RAG-grounded content (cover letter, resume summary, or bullets) with citations."""
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
        result = await generate_content(
            db=db,
            resume_id=str(payload.resume_id),
            jd_id=str(payload.job_description_id),
            content_type=payload.content_type,
            tone=payload.tone,
            length=payload.length,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    return GeneratedContent(**result)
