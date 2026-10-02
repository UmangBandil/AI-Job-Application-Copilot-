"""Fast Apply batch analysis service (M6).

ONE request per form instead of one request per field:

    page scan (extension) → server-side re-classification with confidence
      → job upsert (dedup) → duplicate-application check
      → deterministic safe actions (M4 planner)
      → batch answer generation for eligible questions (M5 engine)
      → bucketed, reviewable result

Confidence gates (Phase 4):
  * ≥ 0.90            → safe: may be filled immediately (still reviewable).
  * 0.70 – 0.89       → review: fillable only after the human sees it.
  * < 0.70 / UNKNOWN  → never auto-filled by the system.

Trust properties (inherited from M4/M5, not re-implemented here):
  * Every fill action is a backend-validated BrowserAction (allow-list).
  * Sensitive questions are never answered and never auto-filled — the
    server re-classifies everything; client labels are advisory only.
  * Password/file fields are never touched by automation.
  * Nothing is submitted — this endpoint only proposes.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.planner import build_fill_plan
from app.ai.agents.answer_agent import generate_answer
from app.ai.agents.field_policy import AnswerPolicy, classify_question, match_profile_key
from app.models import Application, JobDescription, Resume, User
from app.schemas.schemas import (
    FastApplyAlreadyApplied,
    FastApplyAnalyzeRequest,
    FastApplyAnalyzeResponse,
    FastApplyBlockedAction,
    FastApplyFieldClassification,
    FastApplyFieldInput,
    FastApplyGeneratedAnswer,
    FastApplyJob,
    FastApplyReviewAction,
    FieldOption,
    PlannedFieldInput,
)
from app.services.url_guard import validate_public_http_url

# Confidence thresholds (Phase 4).
SAFE_FILL_THRESHOLD = 0.90   # ≥ → may be filled immediately
MIN_FILL_THRESHOLD = 0.70    # below → never auto-filled, review only

# Application statuses that mean "the user already applied" (Phase 12).
_APPLIED_STATUSES = ("applied", "interview", "offer")


def _field_text(field: FastApplyFieldInput) -> str:
    """Best available human text for a field (label > aria > placeholder > name)."""
    return (field.label or field.aria_label or field.placeholder or field.name or "").strip()


# ── Job identity (Phase 12) ───────────────────────────────────────────


async def _upsert_job(
    db: AsyncSession,
    user: User,
    payload: FastApplyAnalyzeRequest,
    page_url: str,
) -> tuple[JobDescription, bool]:
    """Find or create the JobDescription for this application page.

    Dedup order: exact source_url match first, then company+title
    (case-insensitive). Returns (job, created).
    """
    job: JobDescription | None = None

    if page_url:
        res = await db.execute(
            select(JobDescription)
            .where(JobDescription.user_id == user.id, JobDescription.source_url == page_url)
            .order_by(JobDescription.created_at.desc())
            .limit(1)
        )
        job = res.scalar_one_or_none()

    if job is None and payload.company.strip() and payload.job_title.strip():
        res = await db.execute(
            select(JobDescription)
            .where(
                JobDescription.user_id == user.id,
                func.lower(JobDescription.company) == payload.company.strip().lower(),
                func.lower(JobDescription.title) == payload.job_title.strip().lower(),
            )
            .order_by(JobDescription.created_at.desc())
            .limit(1)
        )
        job = res.scalar_one_or_none()

    if job is not None:
        return job, False

    job = JobDescription(
        user_id=user.id,
        title=payload.job_title.strip()[:500] or "Untitled role",
        company=payload.company.strip()[:255],
        raw_text=(payload.job_description or "").strip(),
        source_url=page_url,
        parsed_data={},
    )
    db.add(job)
    await db.flush()
    return job, True


async def _find_existing_application(
    db: AsyncSession,
    user: User,
    job: JobDescription,
) -> FastApplyAlreadyApplied | None:
    """Has the user already applied/interviewed/got an offer for this job?"""
    res = await db.execute(
        select(Application)
        .where(
            Application.user_id == user.id,
            Application.job_description_id == job.id,
            Application.status.in_(_APPLIED_STATUSES),
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None
    return FastApplyAlreadyApplied(
        application_id=row.id,
        status=str(row.status),
        applied_at=row.created_at,
    )


async def _has_resume(db: AsyncSession, user: User) -> bool:
    res = await db.execute(select(Resume.id).where(Resume.user_id == user.id).limit(1))
    return res.scalar_one_or_none() is not None


# ── Batch analysis ────────────────────────────────────────────────────


async def analyze_page(
    db: AsyncSession,
    user: User,
    payload: FastApplyAnalyzeRequest,
) -> FastApplyAnalyzeResponse:
    """Classify and bucket every detected field in ONE pass.

    Never fills anything itself and never submits — the response is a
    proposal whose safe_actions are validated BrowserActions the extension
    may execute after the user clicks Fast Apply.
    """
    # 1. URL safety — same SSRF rules as JD fetching; this URL may be
    #    fetched server-side in later milestones. Raises ValueError.
    page_url = validate_public_http_url(payload.page_url)

    # 2. Job identity + duplicate check (Phase 12).
    job, job_created = await _upsert_job(db, user, payload, page_url)
    already_applied = await _find_existing_application(db, user, job)

    # 3. Server-side classification of every field (client labels advisory).
    classifications: list[FastApplyFieldClassification] = []
    blocked: list[FastApplyBlockedAction] = []
    review: list[FastApplyReviewAction] = []
    planner_fields: list = []          # → M4 planner (deterministic profile fills)
    engine_fields: list[tuple[FastApplyFieldInput, float]] = []  # → M5 answer engine
    conf_by_field: dict[str, float] = {}
    label_by_field: dict[str, str] = {}
    unknown_count = 0

    for field in payload.fields:
        text = _field_text(field)
        policy, reason, confidence = classify_question(text, field.type)
        classifications.append(
            FastApplyFieldClassification(
                field_id=field.field_id,
                label=text,
                type=field.type,
                policy=policy.value,
                reason=reason,
                confidence=confidence,
                required=field.required,
            )
        )
        conf_by_field[field.field_id] = confidence
        label_by_field[field.field_id] = text

        # Credentials and file uploads are never touched by automation,
        # no matter how the field is labeled.
        if field.type == "password":
            blocked.append(FastApplyBlockedAction(
                field_id=field.field_id, label=text, reason="password fields are never filled",
            ))
            continue
        if field.type == "file":
            review.append(FastApplyReviewAction(
                field_id=field.field_id, label=text,
                reason="file upload requires an explicit resume choice",
                confidence=confidence, fill_action=None,
            ))
            continue

        if policy is AnswerPolicy.USER_CONFIRMATION_REQUIRED:
            blocked.append(FastApplyBlockedAction(field_id=field.field_id, label=text, reason=reason))
            continue

        # Without a CSS selector nothing can be filled reliably (Phase 19:
        # stale/missing selector is surfaced, never guessed around).
        if not field.selector.strip():
            review.append(FastApplyReviewAction(
                field_id=field.field_id, label=text,
                reason="no selector — cannot fill reliably",
                confidence=confidence, fill_action=None,
            ))
            continue

        if policy is AnswerPolicy.UNKNOWN or confidence < MIN_FILL_THRESHOLD:
            unknown_count += 1
            review.append(FastApplyReviewAction(
                field_id=field.field_id, label=text,
                reason=reason if policy is AnswerPolicy.UNKNOWN else "confidence below auto-fill threshold",
                confidence=confidence, fill_action=None,
            ))
            continue

        if policy is AnswerPolicy.LLM_GENERATED:
            engine_fields.append((field, confidence))
            continue

        # PROFILE_ONLY / PROFILE_OR_MEMORY
        profile_key = match_profile_key(text)
        if profile_key:
            planner_fields.append(
                PlannedFieldInput(
                    field_id=field.field_id,
                    selector=field.selector,
                    tag=field.tag,
                    type=field.type,
                    label=text,
                    name=field.name,
                    placeholder=field.placeholder,
                    aria_label=field.aria_label,
                    options=[FieldOption(value=o.value, label=o.label) for o in field.options],
                    action="profile",
                    profile_key=profile_key,
                    reason=reason,
                )
            )
        else:
            # Choice fields / experience-length questions without a direct
            # profile mapping: semantic memory reuse and (for choice fields
            # with options) grounded option-matching via the M5 engine.
            engine_fields.append((field, confidence))

    # 4. Deterministic safe fills via the M4 planner (profile + validated
    #    select/checkbox handling). Resulting actions are tiered by the
    #    field's classification confidence.
    safe_actions: list[dict] = []
    if planner_fields:
        plan = await build_fill_plan(db, user, planner_fields)
        for action in plan.plan:
            field_conf = conf_by_field.get(action.get("field_id") or "", 0.0)
            if field_conf >= SAFE_FILL_THRESHOLD:
                safe_actions.append(action)
            else:
                review.append(FastApplyReviewAction(
                    field_id=action.get("field_id") or "",
                    label=label_by_field.get(action.get("field_id") or "", ""),
                    reason="confidence below auto-fill threshold — review before filling",
                    confidence=field_conf,
                    fill_action=action,
                ))
        for item in plan.skipped:
            review.append(FastApplyReviewAction(
                field_id=item.field_id, label=item.label, reason=item.reason,
                confidence=conf_by_field.get(item.field_id, 0.0), fill_action=None,
            ))
        for bucket in (plan.needs_review, plan.needs_ai):
            for item in bucket:
                review.append(FastApplyReviewAction(
                    field_id=item.field_id, label=item.label, reason=item.reason,
                    confidence=conf_by_field.get(item.field_id, 0.0), fill_action=None,
                ))

    # 5. Batch answer generation for eligible questions (M5 engine), capped.
    generated: list[FastApplyGeneratedAnswer] = []
    processed = 0
    deferred_count = 0
    for field, field_conf in engine_fields:
        text = _field_text(field)
        if processed >= payload.max_generated:
            deferred_count += 1
            review.append(FastApplyReviewAction(
                field_id=field.field_id, label=text,
                reason="AI generation limit reached — answer this one yourself",
                confidence=field_conf, fill_action=None,
            ))
            continue
        processed += 1

        result = await generate_answer(
            db,
            user,
            question=text,
            field_type=field.type,
            field_options=[{"value": o.value, "label": o.label} for o in field.options],
            job_description=payload.job_description,
            field_id=field.field_id,
            selector=field.selector,
        )

        if result.answer:
            generated.append(FastApplyGeneratedAnswer(
                field_id=field.field_id,
                question=text,
                answer=result.answer,
                confidence=result.confidence,
                requires_review=result.requires_review,
                source=result.source,
                sources=result.sources,
                notes=result.notes,
                fill_action=result.fill_action,
                memory_match=result.memory_match,
            ))

        proposed = result.fill_action
        if proposed is None:
            review.append(FastApplyReviewAction(
                field_id=field.field_id, label=text,
                reason=result.notes or result.policy_reason or "needs your answer",
                confidence=field_conf, fill_action=None,
            ))
        elif field_conf >= SAFE_FILL_THRESHOLD and not result.requires_review:
            safe_actions.append(proposed)
        else:
            # 0.70–0.89 band, or the engine itself wants review: fillable
            # only after the human sees it.
            review.append(FastApplyReviewAction(
                field_id=field.field_id, label=text,
                reason="review the suggested answer before filling",
                confidence=field_conf, fill_action=proposed,
            ))

    # 6. Warnings — failures and limitations are always visible.
    warnings: list[str] = []
    if unknown_count:
        warnings.append(f"{unknown_count} field(s) could not be classified — left for manual review.")
    if blocked:
        warnings.append(
            f"{len(blocked)} sensitive field(s) — answer these yourself; they are never auto-filled."
        )
    if deferred_count:
        warnings.append(
            f"{deferred_count} field(s) were deferred (AI generation limit of {payload.max_generated})."
        )
    if not await _has_resume(db, user):
        warnings.append("No resume on file — generated answers will have limited context.")
    if not ((payload.job_description or "") + (job.raw_text or "")).strip():
        warnings.append("No job description text available — generated answers may be generic.")
    if already_applied:
        applied_on = (
            already_applied.applied_at.strftime("%Y-%m-%d")
            if already_applied.applied_at
            else "an earlier date"
        )
        warnings.append(f"You already applied to this job on {applied_on}.")

    return FastApplyAnalyzeResponse(
        job=FastApplyJob(
            id=job.id,
            title=job.title,
            company=job.company,
            source_url=job.source_url,
            created=job_created,
        ),
        fields=classifications,
        safe_actions=safe_actions,
        review_actions=review,
        blocked_actions=blocked,
        generated_answers=generated,
        warnings=warnings,
        already_applied=already_applied,
        summary={
            "fields_detected": len(classifications),
            "safe_actions": len(safe_actions),
            "review_actions": len(review),
            "blocked_actions": len(blocked),
            "generated_answers": len(generated),
            "reused_memory": sum(1 for g in generated if g.source == "memory"),
            "deferred": deferred_count,
        },
    )
