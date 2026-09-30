"""Deterministic fill-plan planner.

Turns extension-detected fields into a validated, allow-listed action plan
using ONLY authoritative data: the candidate profile and previously saved
question memory (exact-match). The LLM is never involved at this stage —
unknown/sensitive fields are deferred (needs_ai / needs_review), never
guessed.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.actions import BrowserAction
from app.ai.retrieval.question_memory import normalize_question
from app.ai.retrieval.profile_retriever import get_or_create_profile
from app.models import User
from app.schemas.schemas import (
    FillPlanResponse,
    PlannedFieldInput,
    PlanItem,
)

# profile_key → Profile attribute (with derived accessors below)
_SIMPLE_PROFILE_FIELDS = {
    "full_name": "full_name",
    "email": "email",
    "phone": "phone",
    "linkedin_url": "linkedin_url",
    "github_url": "github_url",
    "portfolio_url": "portfolio_url",
    "location": "location",
}


def _profile_value_for(profile, profile_key: str) -> str | None:
    """Resolve a profile_key to a concrete string value (None = no data)."""
    if profile_key in _SIMPLE_PROFILE_FIELDS:
        value = getattr(profile, _SIMPLE_PROFILE_FIELDS[profile_key], "") or ""
        return value or None

    if profile_key in ("first_name", "last_name"):
        full = (profile.full_name or "").strip()
        if not full:
            return None
        parts = full.split()
        if profile_key == "first_name":
            return parts[0]
        return parts[-1] if len(parts) > 1 else None

    return None


def _select_option_for(field: PlannedFieldInput, value: str) -> str | None:
    """Find the option value matching a profile value (by value or label)."""
    wanted = value.strip().lower()
    for opt in field.options or []:
        if opt.value.strip().lower() == wanted or opt.label.strip().lower() == wanted:
            return opt.value
    return None


async def build_fill_plan(
    db: AsyncSession,
    user: User,
    fields: list[PlannedFieldInput],
) -> FillPlanResponse:
    profile = await get_or_create_profile(db, user)

    # Exact-match question memory for choice/memory fields (no LLM, no
    # embedding call — just the normalized fast path).
    memory_cache: dict[str, str | None] = {}

    async def exact_memory_answer(question: str) -> str | None:
        key = normalize_question(question)
        if key in memory_cache:
            return memory_cache[key]
        from sqlalchemy import select

        from app.models import ApplicationQuestion

        res = await db.execute(
            select(ApplicationQuestion)
            .where(
                ApplicationQuestion.user_id == user.id,
                ApplicationQuestion.normalized_question == key,
            )
            .order_by(ApplicationQuestion.updated_at.desc())
            .limit(1)
        )
        record = res.scalar_one_or_none()
        answer = record.answer if record else None
        memory_cache[key] = answer
        return answer

    actions: list[BrowserAction] = []
    skipped: list[PlanItem] = []
    needs_review: list[PlanItem] = []
    needs_ai: list[PlanItem] = []

    for field in fields:
        if field.action == "review":
            needs_review.append(PlanItem(field_id=field.field_id, label=field.label, reason=field.reason or "sensitive"))
            continue

        if field.action == "profile" and field.profile_key:
            value = _profile_value_for(profile, field.profile_key)
            if not value:
                skipped.append(PlanItem(field_id=field.field_id, label=field.label, reason=f"profile field '{field.profile_key}' is empty"))
                continue

            if field.type == "select":
                option_value = _select_option_for(field, value)
                if option_value is None:
                    skipped.append(PlanItem(field_id=field.field_id, label=field.label, reason=f"no option matches profile value for '{field.profile_key}'"))
                    continue
                actions.append(BrowserAction(action="SELECT", field_id=field.field_id, selector=field.selector, option_value=option_value))
            elif field.type == "checkbox":
                actions.append(
                    BrowserAction(action="CHECK" if value.lower() in ("true", "yes", "1") else "UNCHECK", field_id=field.field_id, selector=field.selector)
                )
            elif field.type == "radio":
                option_value = _select_option_for(field, value)
                if option_value is None:
                    skipped.append(PlanItem(field_id=field.field_id, label=field.label, reason=f"no radio option matches '{field.profile_key}'"))
                    continue
                actions.append(BrowserAction(action="SELECT", field_id=field.field_id, selector=field.selector, option_value=option_value))
            elif field.type == "file":
                skipped.append(PlanItem(field_id=field.field_id, label=field.label, reason="file upload requires explicit resume choice (M7)"))
            else:
                actions.append(BrowserAction(action="FILL", field_id=field.field_id, selector=field.selector, value=value))
            continue

        if field.action == "memory":
            question = field.label or field.name or field.field_id
            answer = await exact_memory_answer(question)
            if answer:
                if field.type == "select":
                    option_value = _select_option_for(field, answer)
                    if option_value is not None:
                        actions.append(BrowserAction(action="SELECT", field_id=field.field_id, selector=field.selector, option_value=option_value))
                        continue
                elif field.type in ("radio", "checkbox"):
                    skipped.append(PlanItem(field_id=field.field_id, label=field.label, reason="memory answer needs confirmation for choice fields"))
                    continue
                else:
                    actions.append(BrowserAction(action="FILL", field_id=field.field_id, selector=field.selector, value=answer))
                    continue
            needs_ai.append(PlanItem(field_id=field.field_id, label=field.label, reason="no saved answer yet"))
            continue

        # ai / unknown
        needs_ai.append(PlanItem(field_id=field.field_id, label=field.label, reason=field.reason or "needs generated answer"))

    return FillPlanResponse(
        plan=[a.model_dump() for a in actions],
        skipped=skipped,
        needs_review=needs_review,
        needs_ai=needs_ai,
        summary={
            "actions": len(actions),
            "skipped": len(skipped),
            "needs_review": len(needs_review),
            "needs_ai": len(needs_ai),
        },
    )
