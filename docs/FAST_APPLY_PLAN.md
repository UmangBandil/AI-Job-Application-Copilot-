# Fast Apply — Evolution Plan

This document answers the Fast Apply specification (28 phases) against the
**existing** codebase and maps it to incremental milestones. It is a living
plan: each milestone updates the checkboxes here and the README status.

> Companion: [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md) (M0 audit) and
> the milestone chain M0–M12 recorded there. M0–M5 are **done** (see below).

---

## A. What already exists (verified, tested)

| Area | Where | State |
|---|---|---|
| FastAPI backend, JWT auth, rate limits | `backend/app/` | working |
| PostgreSQL + pgvector, Alembic migrations (0001–0004) | `backend/alembic/` | working |
| Resume upload → parse → chunk → embed → RAG with citations | `resume_service`, `generation_service` | working |
| JD parsing + resume/JD match scoring (skill + embedding) | `jd_service`, `matching_service` | working |
| LLM provider abstraction (Ollama / OpenAI / Anthropic) | `ai/providers/base.py` | working |
| Candidate profile (authoritative personal facts) | `Profile`, `/api/v1/profile` | working |
| Question memory with semantic retrieval (pgvector) | `ApplicationQuestion`, `ai/retrieval/question_memory.py` | working |
| Form detection (labels/aria/shadow DOM), field classification (client) | `extension/content/form-detector.js`, `field-mapper.js` | working |
| Deterministic fill planner (profile + memory only, LLM-free) | `agent/planner.py`, `POST /agent/fill-plan` | working |
| Validated browser-action allow-list (FILL/SELECT/…/STOP) | `agent/actions.py`, `extension/content/autofill.js` | working |
| Grounded answer engine with policy gate + confidence gating + review fallback | `ai/agents/answer_agent.py`, `field_policy.py`, `POST /agent/answer` | working |
| Accepted-answer memory save | `POST /agent/answers/save` | working |
| Tracker (applications CRUD), job search, dashboard stats | `api/applications.py`, `job_search.py`, `dashboard.py` | working |
| Extension popup (scan/autofill counts), options (backend URL+token) | `extension/popup`, `extension/options` | working |
| Tests: 132 backend + 37 extension (jsdom) | `backend/tests`, `tests/browser` | passing |

### What this already covers from the spec

- Phases 1, 3 (client-side), 5, 6 (storage/retrieval), 7 (pipeline), 17
  (allow-list + validated actions), 18 (generic forms), 21 (SSRF guard,
  sensitive policy), 25 (most entities), 26 (most endpoints), 28 (milestone
  discipline) — **partially or fully**.

### What is genuinely missing

- **Batch analysis** (one request per form instead of per field) — Phase 8/22.
- **Server-side classification confidence** (Phase 4) — the client has no
  numeric confidence; the server policy engine has no UNKNOWN bucket yet.
- **Job identification + duplicate check** (Phase 12) — no upsert of the JD
  from the application page, no "already applied?" answer.
- **Fast Apply button / review screen / edit + accept UI** (Phase 2, 9, 24).
- **Explicit submission gate + CAPTCHA/OTP stop** (Phase 10) — no submit
  flow at all yet; extension never clicks submit.
- **Tracker write-back on submit** (Phase 15) — applications are created
  manually today; no `source_url`, no event timeline.
- **Multi-page sessions** (Phase 11) — NEXT_PAGE exists in the allow-list
  but is a no-op; no session persistence.
- **Resume recommendation** (Phase 14), **analytics extension** (Phase 16),
  **structured event logging** (Phase 23), **prompt-injection test suite**
  (Phase 21 hardening), **Playwright** (Phase 20 browser-level).

## B. What can be reused as-is (do not duplicate)

1. `agent/actions.py` — the action schema is the only thing that may drive
   the browser. Every new path serializes through it.
2. `agent/planner.build_fill_plan` — deterministic profile/memory fill logic
   (M4). The batch analyze endpoint calls it; it is NOT re-implemented.
3. `ai/agents/answer_agent.generate_answer` — the M5 pipeline (policy gate →
   retrieval → LLM → validation → confidence). Batch analyze calls it per
   eligible question; the trust properties stay in one place.
4. `ai/agents/field_policy.py` — server-side sensitive rules; the batch
   endpoint extends it with confidence + UNKNOWN, not a parallel copy.
5. `ai/retrieval/*` — profile and memory retrieval.
6. `services/resume_service` embeddings + `ResumeChunk.embedding` pgvector.
7. `services/url_guard` — page URLs are validated with the same public-URL
   rules before being stored.
8. `JobDescription` + `Application` models — job identity
   (`title/company/source_url`) and tracker rows already exist; Fast Apply
   upserts into them instead of new tables.
9. Extension `form-detector` / `field-mapper` / `autofill` / `answer` /
   `background` broker — extended, never rewritten.

## C. What needs modification (small, surgical)

| File | Change |
|---|---|
| `ai/agents/field_policy.py` | add `UNKNOWN` policy + per-rule classification confidence; return `(policy, reason, confidence)` |
| `ai/agents/answer_agent.py` | UNKNOWN → review fallback (no LLM); add `sources` to the response |
| `extension/content/answer.js` | becomes the batch client (`analyze` payload + apply approved actions) |
| `extension/content/content.js` | `fastApply()` flow: one analyze call → execute safe → queue review |
| `extension/popup/*` | primary ⚡ FAST APPLY button + result summary |
| `api/agent.py` | unchanged (kept for single-question flows) |
| `dashboard.py` | later milestone: role/company/location breakdowns |

## D. What needs to be built (milestones, additive only)

### M6 — Fast Apply batch analysis ✅ DONE (committed)
- `POST /api/v1/fast-apply/analyze` — **one request per form**:
  - validates `page_url`, upserts the `JobDescription` (dedup by URL, else
    company+title), checks for an existing **applied/interview/offer**
    application → `already_applied` + date + application id (Phase 12).
  - re-classifies every field server-side with **confidence** (Phase 3/4):
    PROFILE / MEMORY / RESUME / AI / SENSITIVE / UNKNOWN.
  - safe actions from the M4 planner, confidence-gated:
    ≥0.90 safe · 0.70–0.89 review (still fillable with highlight) ·
    <0.70 never auto-filled.
  - batch answer generation for eligible AI fields (cap `max_generated`,
    default 5), each through the M5 pipeline with `sources` shown.
  - warnings: unknown fields, no resume, no JD text, duplicate application.
- Nothing is submitted; nothing sensitive is answered.

### M7 — Extension Fast Apply UX + review screen (Phases 2, 6-UI, 9, 24)
- ⚡ FAST APPLY button → one analyze call → execute `safe_actions` →
  review screen: per-field rows, AI answers with edit/accept (accept →
  `/agent/answers/save`, then fill), "reused previous answer" prompt with
  use/edit/regenerate options, counts summary.
- Fill application → "Review Application" state (no submit yet).

### M8 — Safe submission + tracker write-back (Phases 10, 15, 23)
- `POST /api/v1/fast-apply/submit`: explicit confirmation required; blocks
  submission when the page reports CAPTCHA/OTP/payment fields; creates the
  `Application` (status `applied`) linked to JD + chosen resume; records
  `application_events` (migration 0005); returns the tracker row.
- Extension: [Cancel]/[Submit] confirmation; CAPTCHA/anti-bot detection →
  STOP + "Human action required."; never fills passwords/OTP/payment.

### M9 — Multi-page sessions (Phase 11)
- `fast_apply_sessions` + `fast_apply_fields` tables (migration 0006);
  `POST /fast-apply/session/{id}/page` after each page scan; resume/continue
  or stop with a clear "continue manually" message.

### M10 — Resume recommendation + match card (Phases 13, 14)
- Recommend best-matching resume for the detected job (reuses
  `matching_service` + in-DB cosine); user confirms; match breakdown shown
  (skills matched/missing, no fabrication).

### M11 — Analytics + observability (Phases 16, 23)
- Dashboard: applications by role/company/location, interview rate, top
  missing skills — all computed from stored rows.
- Structured events (`fast_apply_started` … `application_failed`) with a
  strict no-secrets policy.

### M12 — Hardening (Phase 21) + Playwright (Phase 20)
- Prompt-injection tests (malicious JD/labels), extension XSS review,
  token handling review, python-jose → PyJWT; Playwright end-to-end against
  local fixtures only.

## E–H. File / DB / API / extension changes (this milestone M6)

- **Files added:** `backend/app/services/fast_apply_service.py`,
  `backend/app/api/fast_apply.py`, `backend/tests/test_fast_apply.py`,
  `docs/FAST_APPLY_PLAN.md`.
- **Files modified:** `ai/agents/field_policy.py`, `ai/agents/answer_agent.py`,
  `schemas/schemas.py`, `main.py`, `tests/test_answer_agent.py`, `README.md`.
- **Database:** **no migration** — job identity reuses `job_descriptions`
  (`title/company/source_url/raw_text/parsed_data`); dedup reuses
  `applications`. New tables are deferred to M8/M9 as listed.
- **API:** additive only — `POST /api/v1/fast-apply/analyze`. Existing 36
  operations unchanged.
- **Extension:** unchanged this milestone (M7 wires it to the new endpoint).

## I. Test plan

- Backend (new): confidence table per rule; UNKNOWN never auto-fills and
  never reaches the LLM; sensitive stays blocked even with client claims;
  analyze happy path (safe/review/blocked/generated buckets); job upsert
  dedup by URL and by company+title; duplicate application detection;
  `max_generated` cap; warnings (no resume / no JD / unknown fields);
  auth required; OpenAPI registration.
- Backend (regression): existing 132 tests stay green (policy signature
  change updated at call sites). Final M6 counts: **153 backend** (21 new
  Fast Apply tests) + **37 extension** — all passing.
- Extension (M7): jsdom tests for the batch client and review actions.
- No real job sites, no live LLM/DB: fake sessions + fake providers, as in
  M1–M5.

## Safety invariants (must hold in every milestone)

1. The LLM never executes anything — it may only produce text that becomes a
   Pydantic-validated `BrowserAction` or nothing.
2. Sensitive questions (work auth, sponsorship, salary, demographics,
   notice period, relocation, travel) are never LLM-answered, never
   auto-filled, and never saved to memory automatically.
3. Nothing is submitted without an explicit human click; CAPTCHA/OTP/MFA
   stops the flow; passwords/payment data are never filled.
4. Webpage content (labels, JD text) is untrusted input; it cannot override
   system instructions or profile facts.
5. No fabricated facts: every generated answer is grounded in profile /
   resume / memory or returns `insufficient_context`.
6. Failures are visible: counts and reasons are always shown, never a fake
   "success".
