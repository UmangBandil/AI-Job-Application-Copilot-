"""Application memory API — persistent question/answer reuse."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.retrieval.question_memory import find_similar_questions, save_answer
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import ApplicationQuestion, User
from app.schemas.schemas import (
    MemoryAnswerCreate,
    MemoryAnswerResponse,
    MemoryAnswerUpdate,
    MemorySearchResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/search", response_model=MemorySearchResponse)
async def search_memory(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find previous answers for semantically similar questions."""
    matches = await find_similar_questions(db, user, q, limit=limit)
    return MemorySearchResponse(query=q, matches=matches)


@router.get("/answers", response_model=list[MemoryAnswerResponse])
async def list_answers(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recently saved question/answer pairs."""
    result = await db.execute(
        select(ApplicationQuestion)
        .where(ApplicationQuestion.user_id == user.id)
        .order_by(ApplicationQuestion.updated_at.desc())
        .limit(limit)
    )
    return [MemoryAnswerResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/answers", response_model=MemoryAnswerResponse, status_code=201)
async def create_answer(
    payload: MemoryAnswerCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a question/answer pair to memory (embedded for future reuse)."""
    record = await save_answer(
        db,
        user.id,
        payload.question,
        payload.answer,
        source=payload.source,
        confidence=payload.confidence,
        context=payload.context,
    )
    return MemoryAnswerResponse.model_validate(record)


@router.patch("/answers/{answer_id}", response_model=MemoryAnswerResponse)
async def update_answer(
    answer_id: str,
    payload: MemoryAnswerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a saved answer (e.g. after the user edits a generated one)."""
    result = await db.execute(
        select(ApplicationQuestion).where(
            ApplicationQuestion.id == answer_id,
            ApplicationQuestion.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Answer not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "answer" in update_data:
        # An edited answer becomes user-authored — it is now human-approved.
        update_data.setdefault("source", "user")
        update_data.setdefault("confidence", 1.0)
    for field, value in update_data.items():
        setattr(record, field, value)

    await db.flush()
    await db.refresh(record)
    return MemoryAnswerResponse.model_validate(record)
