"""Agent API — plans and answers the extension may use.

The fill-plan endpoint is deliberately LLM-free: deterministic profile +
memory fills only. The answer endpoint (M5) adds grounded LLM generation:
every response is policy-checked, review-gated, and its fill_action — when
present — is a backend-validated BrowserAction. The LLM never produces
free-form output that reaches the browser.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.planner import build_fill_plan
from app.ai.agents.answer_agent import generate_answer
from app.ai.retrieval.question_memory import save_answer
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.schemas import (
    AnswerProposal,
    AnswerRequest,
    FillPlanRequest,
    FillPlanResponse,
    SaveAnswerRequest,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/fill-plan", response_model=FillPlanResponse)
async def create_fill_plan(
    payload: FillPlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Turn detected fields into a validated, allow-listed action plan.

    Profile fields fill deterministically; sensitive fields are deferred
    for human review; unknown fields wait for the answer engine.
    """
    return await build_fill_plan(db, user, payload.fields)


@router.post("/answer", response_model=AnswerProposal)
async def answer_question(
    payload: AnswerRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Propose a review-gated answer for ONE application question.

    Sensitive questions (work auth, salary, sponsorship, demographics,
    notice period, relocation, travel) are NEVER answered by the LLM —
    they always come back requires_review with no answer. Generated
    answers are proposals only: they are saved to memory via
    /agent/answers/save once the user accepts them.
    """
    return await generate_answer(
        db,
        user,
        question=payload.question,
        field_type=payload.field_type,
        field_options=[o.model_dump() for o in payload.field_options],
        job_description=payload.job_description,
        client_policy=payload.client_policy,
        field_id=payload.field_id,
        selector=payload.selector,
        max_chars=payload.max_chars,
    )


@router.post("/answers/save", response_model=AnswerProposal)
async def save_accepted_answer(
    payload: SaveAnswerRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store a user-accepted answer in question memory.

    Typically called after a human reviews/edits an LLM proposal; saving
    promotes it to source='user' so future similar questions reuse it
    deterministically (user > memory > profile > llm authority).
    """
    await save_answer(
        db,
        user.id,
        question=payload.question,
        answer=payload.answer,
        source=payload.source,
        confidence=payload.confidence,
        context=payload.context,
    )
    return AnswerProposal(
        question=payload.question,
        policy="saved",
        answer=payload.answer,
        confidence=payload.confidence,
        requires_review=False,
        source=payload.source,
        policy_reason="accepted by user",
        notes="Saved to question memory.",
    )
