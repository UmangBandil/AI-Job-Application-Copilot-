"""Resume upload and management API routes."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Resume, ResumeChunk, User
from app.schemas.schemas import ResumeResponse
from app.services.resume_service import extract_text, parse_resume, chunk_resume, embed_texts

router = APIRouter(prefix="/resumes", tags=["resumes"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("", response_model=ResumeResponse, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    title: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload and process a resume (PDF, DOCX, or TXT)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported format. Use: {', '.join(ALLOWED_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # Extract text
    try:
        raw_text = extract_text(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract text: {str(e)}")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="No text content extracted from file")

    # Parse into structured data
    parsed_data = parse_resume(raw_text)

    # Create resume record
    resume = Resume(
        user_id=user.id,
        title=title or file.filename,
        file_name=file.filename,
        raw_text=raw_text,
        parsed_data=parsed_data,
    )
    db.add(resume)
    await db.flush()

    # Chunk and embed
    chunk_data_list = chunk_resume(parsed_data, raw_text)
    texts = [c["chunk_text"] for c in chunk_data_list]
    embeddings = embed_texts(texts) if texts else []

    for i, chunk_data in enumerate(chunk_data_list):
        chunk = ResumeChunk(
            resume_id=resume.id,
            chunk_text=chunk_data["chunk_text"],
            chunk_type=chunk_data["chunk_type"],
            metadata_=chunk_data.get("metadata_", {}),
            embedding=embeddings[i] if i < len(embeddings) else None,
        )
        db.add(chunk)

    await db.flush()
    await db.refresh(resume)

    # Add chunk count
    resume_dict = ResumeResponse.model_validate(resume).model_dump()
    resume_dict["chunk_count"] = len(chunk_data_list)
    return ResumeResponse(**resume_dict)


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all resumes for the current user."""
    result = await db.execute(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
    )
    resumes = result.scalars().all()

    response = []
    for r in resumes:
        count_result = await db.execute(
            select(func.count(ResumeChunk.id)).where(ResumeChunk.resume_id == r.id)
        )
        chunk_count = count_result.scalar() or 0
        resume_dict = ResumeResponse.model_validate(r).model_dump()
        resume_dict["chunk_count"] = chunk_count
        response.append(ResumeResponse(**resume_dict))

    return response


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific resume."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    count_result = await db.execute(
        select(func.count(ResumeChunk.id)).where(ResumeChunk.resume_id == resume.id)
    )
    chunk_count = count_result.scalar() or 0

    resume_dict = ResumeResponse.model_validate(resume).model_dump()
    resume_dict["chunk_count"] = chunk_count
    return ResumeResponse(**resume_dict)


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a resume and all its chunks."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    await db.delete(resume)
