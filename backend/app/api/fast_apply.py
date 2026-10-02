"""Fast Apply API (M6) — batch form analysis.

ONE request per application form: server-side field classification with
confidence, deterministic safe fills via the M4 planner, batch grounded
answer generation via the M5 engine, duplicate-application detection, and
transparent warnings. Nothing is filled or submitted by this endpoint —
the response is a proposal for human review.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.schemas import FastApplyAnalyzeRequest, FastApplyAnalyzeResponse
from app.services.fast_apply_service import analyze_page

router = APIRouter(prefix="/fast-apply", tags=["fast-apply"])


@router.post("/analyze", response_model=FastApplyAnalyzeResponse)
async def analyze(
    payload: FastApplyAnalyzeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze a detected application form in ONE batched request.

    Returns per-field classifications (with confidence), safe-to-fill
    actions (validated BrowserActions), review/blocked buckets, generated
    answers, duplicate-application status, and warnings. Safe threshold:
    ≥ 0.90 fills immediately, 0.70–0.89 fills only after review, anything
    below — or sensitive, password, file, or unclassifiable — never
    auto-fills.
    """
    try:
        return await analyze_page(db, user, payload)
    except ValidationError:
        # Pydantic ValidationError subclasses ValueError — internal schema
        # bugs must surface as real errors, not a misleading 400.
        raise
    except ValueError as e:
        # URL validation failures (unparseable, private, non-http).
        raise HTTPException(status_code=400, detail=str(e)) from e
