"""Agent API — plans the extension may execute.

The fill-plan endpoint is deliberately LLM-free: deterministic profile +
memory fills only. Generated answers arrive via /api/v1/agent/answer in
Milestone 5 and pass through the same validated action schema.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.planner import build_fill_plan
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.schemas import FillPlanRequest, FillPlanResponse

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/fill-plan", response_model=FillPlanResponse)
async def create_fill_plan(
    payload: FillPlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Turn detected fields into a validated, allow-listed action plan.

    Profile fields fill deterministically; sensitive fields are deferred
    for human review; unknown fields wait for the answer engine (M5).
    """
    return await build_fill_plan(db, user, payload.fields)
