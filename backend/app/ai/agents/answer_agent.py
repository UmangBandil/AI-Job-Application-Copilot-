"""Answer engine agent (M5).

Pipeline for ONE application question:

    policy gate → memory retrieval → profile context → resume retrieval
      → (LLM_GENERATED only) grounded generate_json with schema validation
        and one retry-with-error → confidence gating → requires_review fallback

Trust properties:
  * Sensitive questions never reach the LLM (policy gate first); UNKNOWN
    fields (no recognizable label) never reach the LLM either.
  * LLM output is validated into a narrow Pydantic shape; invalid output
    downgrades to requires_review rather than flowing anywhere.
  * The response's fill_action is a backend-validated BrowserAction — the
    raw LLM string never controls the browser directly.
  * `sources` records what the proposal was grounded in (profile / memory /
    resume / job_description / llm) so the review UI can show provenance.
"""

import logging
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.actions import BrowserAction
from app.ai.agents.field_policy import (
    AnswerPolicy,
    classify_question,
    client_policy_matches,
    match_profile_key,
)
from app.ai.prompts.form_answer import ANSWER_SYSTEM_PROMPT, build_answer_prompt
from app.ai.retrieval.profile_retriever import (
    build_profile_context,
    get_or_create_profile,
    profile_context_as_text,
)
from app.ai.retrieval.question_memory import find_similar_questions
from app.ai.providers.base import LLMError, get_llm_provider
from app.models import Profile, ResumeChunk, Resume, User
from app.services.resume_service import embed_query

logger = logging.getLogger(__name__)

# Confidence at or below this → requires_review=True.
LOW_CONFIDENCE_THRESHOLD = 0.5

# Model-returned answers that mean "I don't know" — guarded against being
# treated as literal content.
_NO_ANSWER = "insufficient_context"
_DECLINED = "declined"


# ── Response model ────────────────────────────────────────────────────


class AnswerResponse(BaseModel):
    """Review-gated answer proposal for one application question."""

    question: str
    policy: str
    answer: str | None = None
    confidence: float = 0.0
    requires_review: bool = True
    source: str = "none"  # none | profile | memory | llm
    sources: list[str] = []  # provenance: profile | memory | resume | job_description | llm
    policy_reason: str = ""
    notes: str = ""
    fill_action: dict | None = None  # validated BrowserAction, or None
    memory_match: dict | None = None
    llm_raw: str | None = None
    anomalies: list[str] = []


# ── LLM response contract ─────────────────────────────────────────────


class LLMAnswerDraft(BaseModel):
    """Narrow validated shape the LLM must return."""

    answer: str = Field(min_length=1, max_length=5000)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    notes: str = Field(default="", max_length=500)


# ── Profile value resolution (mirrors planner logic) ──────────────────

_SIMPLE_PROFILE_FIELDS = {
    "full_name": "full_name",
    "email": "email",
    "phone": "phone",
    "linkedin_url": "linkedin_url",
    "github_url": "github_url",
    "portfolio_url": "portfolio_url",
    "location": "location",
}


def _profile_value_for(profile: Profile, profile_key: str) -> str | None:
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


def _match_option(options: list[dict] | None, value: str) -> str | None:
    """Find the option value matching an answer (by value or label)."""
    if not options:
        return None
    wanted = (value or "").strip().lower()
    if not wanted:
        return None
    for opt in options:
        v = (opt.get("value") or "").strip().lower()
        label = (opt.get("label") or "").strip().lower()
        if wanted in (v, label):
            return opt.get("value")
    return None


def _build_fill_action(
    field_type: str,
    field_options: list[dict] | None,
    answer: str,
    field_id: str | None,
    selector: str | None,
) -> dict | None:
    """Wrap an answer in a validated BrowserAction.

    For select/radio the answer must match one of the provided options
    (value or label, case-insensitive); otherwise the answer is rejected
    (None) rather than being guessed onto the page.
    """
    value = (answer or "").strip()
    if not value:
        return None

    if field_type in ("select", "radio"):
        option_value = _match_option(field_options, value)
        if option_value is None:
            return None
        try:
            return BrowserAction(
                action="SELECT", field_id=field_id, selector=selector, option_value=option_value
            ).model_dump()
        except ValidationError:
            return None

    if field_type == "checkbox":
        checked = value.lower() in ("yes", "true", "1", "checked")
        action = "CHECK" if checked else "UNCHECK"
        try:
            return BrowserAction(action=action, field_id=field_id, selector=selector).model_dump()
        except ValidationError:
            return None

    try:
        return BrowserAction(action="FILL", field_id=field_id, selector=selector, value=value).model_dump()
    except ValidationError:
        return None


# ── Retrieval steps ───────────────────────────────────────────────────


async def _retrieve_memory(db: AsyncSession, user: User, question: str) -> list[dict]:
    try:
        return await find_similar_questions(db, user, question, limit=3, min_similarity=0.80)
    except Exception as e:  # noqa: BLE001 — memory miss must never kill the pipeline
        logger.warning("memory retrieval failed for user %s: %s", user.id, e)
        return []


async def _retrieve_resume_chunks(
    db: AsyncSession,
    user_id: UUID,
    question: str,
    limit: int = 4,
) -> list[dict]:
    """Semantic search over the user's resume chunks via pgvector.

    Failure is non-fatal: no resume chunks → empty excerpts, and the LLM
    falls back to insufficient_context instead of inventing facts.
    """
    try:
        query_vec = embed_query(question)
    except Exception as e:  # noqa: BLE001 — no embedding model available
        logger.warning("resume embedding unavailable: %s", e)
        return []

    distance = ResumeChunk.embedding.cosine_distance(query_vec)
    try:
        res = await db.execute(
            select(ResumeChunk, Resume, distance.label("distance"))
            .join(Resume, ResumeChunk.resume_id == Resume.id)
            .where(Resume.user_id == user_id, ResumeChunk.embedding.isnot(None))
            .order_by(distance)
            .limit(limit)
        )
        rows = res.all()
    except Exception as e:  # noqa: BLE001
        logger.warning("resume chunk retrieval failed: %s", e)
        return []

    return [
        {"chunk_type": chunk.chunk_type, "chunk_text": chunk.chunk_text[:800], "resume_title": resume.title}
        for chunk, resume, _dist in rows
    ]


# ── LLM call with one retry-with-error ────────────────────────────────


async def _generate_draft_via_llm(
    prompt: str,
    field_options: list[str] | None,
    provider,
) -> tuple[LLMAnswerDraft | None, str | None]:
    """Call provider.generate_json, validate against LLMAnswerDraft.

    One retry: on invalid output the validation error text is fed back to
    the model once. Returns (draft, None) on success or (None, last_error).
    """
    feedback = ""
    last_error = None

    for _attempt in range(2):
        attempt_prompt = prompt + (
            f"\n\nYour previous reply was invalid: {feedback}\nReturn ONLY the corrected JSON object."
            if feedback
            else ""
        )
        try:
            raw = await provider.generate_json(attempt_prompt, system=ANSWER_SYSTEM_PROMPT, max_tokens=400)
        except LLMError as e:
            return None, str(e)

        answer = str(raw.get("answer", "")).strip()
        try:
            conf = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5

        # Choice fields: the answer must be one of the allowed options
        # (case-insensitive, by label or value).
        if field_options and answer:
            matched = next((o for o in field_options if o.strip().lower() == answer.lower()), None)
            if matched is None:
                last_error = f"answer {answer!r} is not one of the allowed options"
                feedback = last_error
                continue
            answer = matched

        try:
            draft = LLMAnswerDraft(
                answer=answer,
                confidence=conf,
                notes=str(raw.get("notes", ""))[:500],
            )
            return draft, None
        except ValidationError as e:
            last_error = str(e.errors(include_url=False))
            feedback = last_error

    return None, last_error


# ── Main entry point ──────────────────────────────────────────────────


async def generate_answer(
    db: AsyncSession,
    user: User,
    question: str,
    field_type: str = "text",
    field_options: list[dict] | None = None,
    job_description: str = "",
    client_policy: str | None = None,
    client_anomaly: str | None = None,
    field_id: str | None = None,
    selector: str | None = None,
    max_chars: int = 500,
) -> AnswerResponse:
    """Produce a review-gated answer proposal for one question."""
    # 1. Policy gate — sensitive topics and unclassifiable fields never
    # reach the LLM.
    policy, policy_reason, _policy_confidence = classify_question(question, field_type)

    def _anomalies(extra: str | None = None) -> list[str]:
        return [a for a in (client_anomaly, extra) if a]

    # Server policy always wins; disagreement with the client's mapper is
    # recorded on every path (a tampered or buggy client cannot silently
    # downgrade a sensitive question).
    anomaly_note = None
    if client_policy and not client_policy_matches(policy, client_policy):
        anomaly_note = f"client classified as {client_policy!r}, server policy is {policy.value}"

    if policy is AnswerPolicy.USER_CONFIRMATION_REQUIRED:
        return AnswerResponse(
            question=question,
            policy=policy.value,
            answer=None,
            confidence=0.0,
            requires_review=True,
            source="none",
            policy_reason=policy_reason,
            notes=f"Sensitive topic ({policy_reason}) — answer this yourself.",
            anomalies=_anomalies(anomaly_note),
        )

    if policy is AnswerPolicy.UNKNOWN:
        return AnswerResponse(
            question=question,
            policy=policy.value,
            answer=None,
            confidence=0.0,
            requires_review=True,
            source="none",
            policy_reason=policy_reason,
            notes="Field could not be classified — answer this yourself.",
            anomalies=_anomalies(anomaly_note),
        )

    # 2. Memory retrieval.
    memory = await _retrieve_memory(db, user, question)

    # 3. Profile context.
    profile = await get_or_create_profile(db, user)

    # 4. Resume retrieval (only when LLM generation is possible/needed).
    resume_excerpts: list[dict] = []
    if policy in (AnswerPolicy.LLM_GENERATED, AnswerPolicy.RESUME_REQUIRED):
        resume_excerpts = await _retrieve_resume_chunks(db, user.id, question)

    # 5. Deterministic paths first (profile, then memory).
    if policy in (AnswerPolicy.PROFILE_ONLY, AnswerPolicy.PROFILE_OR_MEMORY):
        profile_key = match_profile_key(question)
        if profile_key:
            value = _profile_value_for(profile, profile_key)
            if value:
                return AnswerResponse(
                    question=question,
                    policy=policy.value,
                    answer=value,
                    confidence=1.0,
                    requires_review=False,
                    source="profile",
                    sources=["profile"],
                    policy_reason=policy_reason,
                    fill_action=_build_fill_action(field_type, field_options, value, field_id, selector),
                    notes=f"Filled from profile field '{profile_key}'.",
                    anomalies=_anomalies(anomaly_note),
                )
        if policy is AnswerPolicy.PROFILE_OR_MEMORY:
            if memory:
                top = memory[0]
                return AnswerResponse(
                    question=question,
                    policy=policy.value,
                    answer=top["answer"],
                    confidence=float(top.get("confidence") or 0.9),
                    requires_review=False,
                    source="memory",
                    sources=["memory"],
                    policy_reason=policy_reason,
                    fill_action=_build_fill_action(field_type, field_options, top["answer"], field_id, selector),
                    notes=f"Reused saved answer (similarity {top.get('similarity', 0):.2f}).",
                    memory_match=top,
                    anomalies=_anomalies(anomaly_note),
                )
            if field_options:
                # Choice field with explicit options and no saved answer:
                # fall through to grounded LLM proposal — the answer must
                # match one of the allowed options verbatim, so nothing is
                # invented.
                pass
            else:
                # No options and no data: there is nothing safe to generate.
                return AnswerResponse(
                    question=question,
                    policy=policy.value,
                    answer=None,
                    confidence=0.0,
                    requires_review=True,
                    source="none",
                    policy_reason=policy_reason,
                    notes="No profile value or saved answer — answer this yourself.",
                    anomalies=_anomalies(anomaly_note),
                )
        else:
            # PROFILE_ONLY with no profile value stays strict: no memory,
            # no LLM.
            return AnswerResponse(
                question=question,
                policy=policy.value,
                answer=None,
                confidence=0.0,
                requires_review=True,
                source="none",
                policy_reason=policy_reason,
                notes=f"Profile field '{profile_key}' is empty — answer this yourself.",
                anomalies=_anomalies(anomaly_note),
            )

    # 6. LLM_GENERATED — grounded generation.
    allowed_labels = [
        o.get("label") or o.get("value") for o in (field_options or []) if isinstance(o, dict)
    ]

    system = ANSWER_SYSTEM_PROMPT
    if policy is AnswerPolicy.RESUME_REQUIRED:
        system += (
            "\n\nSPECIAL INSTRUCTION: This question may only be answered from "
            "RESUME EXCERPTS. If they do not contain the needed fact, return "
            "'insufficient_context'."
        )

    profile_ctx_text = profile_context_as_text(profile)
    prompt = build_answer_prompt(
        question=question,
        profile_context=profile_ctx_text,
        memory_matches=memory,
        resume_excerpts=resume_excerpts,
        job_description=job_description,
        field_type=field_type,
        field_options=allowed_labels,
        max_chars=max_chars,
    )

    # Provenance: what this proposal was actually grounded in.
    sources = ["llm"]
    if profile_ctx_text.strip():
        sources.append("profile")
    if memory:
        sources.append("memory")
    if resume_excerpts:
        sources.append("resume")
    if (job_description or "").strip():
        sources.append("job_description")

    provider = get_llm_provider()
    draft, llm_error = await _generate_draft_via_llm(prompt, allowed_labels or None, provider)

    if draft is None:
        return AnswerResponse(
            question=question,
            policy=policy.value,
            answer=None,
            confidence=0.0,
            requires_review=True,
            source="none",
            policy_reason=policy_reason,
            notes=f"LLM unavailable or invalid output: {str(llm_error)[:300]}",
            anomalies=_anomalies(anomaly_note),
        )

    # Guarded no-answer outcomes → review fallback.
    if draft.answer.strip().lower() in (_NO_ANSWER, _DECLINED):
        return AnswerResponse(
            question=question,
            policy=policy.value,
            answer=None,
            confidence=draft.confidence,
            requires_review=True,
            source="llm",
            sources=sources,
            policy_reason=policy_reason,
            notes=draft.notes or "Model reported insufficient context.",
            llm_raw=draft.answer,
            anomalies=_anomalies(anomaly_note),
        )

    # 7. Confidence gating — low-confidence answers need human review and
    # never get a fill action.
    low = draft.confidence <= LOW_CONFIDENCE_THRESHOLD
    return AnswerResponse(
        question=question,
        policy=policy.value,
        answer=draft.answer,
        confidence=draft.confidence,
        requires_review=low,
        source="llm",
        sources=sources,
        policy_reason=policy_reason,
        fill_action=None if low else _build_fill_action(field_type, field_options, draft.answer, field_id, selector),
        notes=draft.notes,
        memory_match=memory[0] if memory else None,
        anomalies=_anomalies(anomaly_note),
    )
