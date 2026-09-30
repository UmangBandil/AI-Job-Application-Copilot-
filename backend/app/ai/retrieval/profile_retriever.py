"""Profile retrieval for the answer engine.

Converts the authoritative Profile row into structured context that gets
injected into LLM prompts. Only facts present on the profile appear here —
the LLM never sees invented values and is instructed to stay silent about
missing fields.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile, User


async def get_or_create_profile(db: AsyncSession, user: User) -> Profile:
    result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        # Explicit defaults so the object is fully valid even before the DB
        # applies its own column defaults (e.g. during flush-time serialization).
        profile = Profile(
            user_id=user.id,
            full_name="",
            email="",
            phone="",
            location="",
            website="",
            linkedin_url="",
            github_url="",
            portfolio_url="",
            education=[],
            experience=[],
            skills=[],
            projects=[],
            work_authorization={},
            notice_period="",
            salary_expectation="",
            willing_to_relocate=None,
            preferred_locations=[],
        )
        db.add(profile)
        await db.flush()
        await db.refresh(profile)
    return profile


def build_profile_context(profile: Profile) -> dict:
    """Build a structured context dict from the profile for prompt assembly.

    Empty values are omitted so the prompt contains only real facts.
    """
    context: dict = {}

    simple_fields = {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        "website": profile.website,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "portfolio_url": profile.portfolio_url,
        "notice_period": profile.notice_period,
        "salary_expectation": profile.salary_expectation,
    }
    for key, value in simple_fields.items():
        if value:
            context[key] = value

    if profile.skills:
        context["skills"] = list(profile.skills)
    if profile.education:
        context["education"] = profile.education
    if profile.experience:
        context["experience"] = profile.experience
    if profile.projects:
        context["projects"] = profile.projects
    if profile.work_authorization:
        context["work_authorization"] = profile.work_authorization
    if profile.preferred_locations:
        context["preferred_locations"] = list(profile.preferred_locations)
    if profile.willing_to_relocate is not None:
        context["willing_to_relocate"] = profile.willing_to_relocate

    return context


def profile_context_as_text(profile: Profile) -> str:
    """Human-readable profile context for LLM prompts (JSON)."""
    import json

    return json.dumps(build_profile_context(profile), indent=2, default=str)
