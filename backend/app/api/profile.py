"""Candidate profile API — the authoritative source of personal facts.

The profile is what deterministic autofill and the answer engine read;
the LLM is never allowed to invent values that live here.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.retrieval.profile_retriever import get_or_create_profile
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.schemas import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's profile (created empty on first access)."""
    profile = await get_or_create_profile(db, user)
    return ProfileResponse.model_validate(profile)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update profile fields. Only provided fields are changed."""
    profile = await get_or_create_profile(db, user)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.flush()
    await db.refresh(profile)
    return ProfileResponse.model_validate(profile)
