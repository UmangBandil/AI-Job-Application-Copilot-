# Architecture Audit — AI Job Application Copilot

**Milestone 0 deliverable.** Produced before any code changes. Audit date: 2026-09-30.
Baseline commit: `2d282b8` ("fix: address 6 correctness and security defects found in adversarial review"), branch `main`, working tree clean.

**Purpose:** establish ground truth of the existing codebase and map it against the target architecture — a *local-first, FastApply-style AI Job Application Agent* (Ollama reasoning + Chrome extension hands + FastAPI brain + PostgreSQL/pgvector memory + human-in-the-loop submission).

---

## 0. Audit method and verification log

What was inspected: every backend module (`main.py`, `core/*`, `models/models.py`, all 7 `api/*` routers, all 5 `services/*`, `schemas/schemas.py`), the frontend (entry, router, auth context, API client, page list), all Docker/infra files (`docker-compose.yml`, `docker-compose.production.yml`, `backend/Dockerfile`, `backend/Dockerfile.production`, `frontend/Dockerfile`, `render.yaml`), `.env.example`, `README.md`, and `alembic.ini`/`alembic/env.py`.

Commands run during this audit and their results:

| Check | Result |
|---|---|
| `git status` / `git log` | clean tree on `main`; 4 commits, pushed |
| `cd frontend && npm run build` (vite build) | ✅ succeeds |
| `cd frontend && npm run lint` (oxlint, 104 rules) | ✅ 0 errors, 8 warnings |
| `python -c "from app.main import app"` | ✅ imports cleanly |
| OpenAPI enumeration of `app` | ✅ 23 API operations across 17 paths |
| `pytest --version` | pytest 9.1.1 installed (no tests exist yet) |

**Environment limitation (honest scope note):** Docker daemon is not running on this machine and no local PostgreSQL instance exists, so a live end-to-end run (DB writes, auth flow, resume upload, embedding) could **not** be exercised in this audit. Everything below marked "verified" is verified by build/import/OpenAPI inspection and by the earlier behavioral verification session (handlers exercised via `httpx.ASGITransport` with a fake session; production bundle grep; live Vite preview). Claims that were *not* executed end-to-end are marked as such.

---

## 1. Current architecture

### 1.1 High-level shape

```
React 19 + Vite SPA (frontend/, dev :5173, prod served by backend)
        │  axios, baseURL /api/v1 (dev: vite proxy → :8000)
        ▼
FastAPI (backend/app/main.py)  ── prefix /api/v1, 7 routers, 23 operations
        │
        ├── core/   config (pydantic-settings), database (async SQLAlchemy),
        │           deps (JWT → get_current_user), security (jose + passlib)
        ├── models/ 7 ORM models (User, Resume, ResumeChunk, JobDescription,
        │           MatchScore, Application, JobSearchResult)
        ├── schemas/ Pydantic v2 request/response models
        ├── services/ resume_service (parse/chunk/embed), jd_service (parse/fetch),
        │           matching_service (60% keyword + 40% cosine),
        │           generation_service (RAG + Anthropic/OpenAI), job_search_service
        ▼
PostgreSQL 16 + pgvector image (docker), accessed via asyncpg
```

Key request-flow facts (verified by reading code):

- **Startup:** `lifespan` → `init_db()` → `Base.metadata.create_all`. Alembic is scaffolded (`alembic.ini`, `alembic/env.py` wired to `Base.metadata`) but **has no `versions/` directory** — zero migrations exist; schema comes exclusively from `create_all`.
- **Session lifecycle:** `get_db()` yields a session and **commits after every request** (including read-only GETs), rolling back on exception.
- **Auth:** JWT HS256 via `python-jose`, bcrypt via passlib, `HTTPBearer` dependency on every protected route. Ownership checks (`user_id == user.id`) exist on all object-fetching routes (fixed in `2d282b8`).
- **Embeddings:** `sentence-transformers` `all-MiniLM-L6-v2` (384-dim), lazy-loaded singleton on first `embed_texts`/`embed_query` call. Stored in `ResumeChunk.embedding` as **`ARRAY(Float)`, not pgvector** — similarity is computed in numpy in Python after loading all chunks for a resume.
- **LLM:** hard-coded inside `generation_service._call_llm` — Anthropic `claude-sonnet-4-20250514` if `ANTHROPIC_API_KEY` set, else OpenAI `gpt-4o` if `OPENAI_API_KEY` set, else `RuntimeError`. No provider abstraction, no timeout, clients constructed per request.
- **Frontend:** React Router 7 with `ProtectedRoute`/`PublicRoute`; JWT + user persisted in `localStorage`; global 401 interceptor clears session and redirects to `/login`. Pages: Dashboard, Resumes, JobDescriptions, Analyze, Tracker (Kanban), JobSearch, Login/Register.
- **Production deploy:** `backend/Dockerfile.production` multi-stage build (Node builds SPA → copied to `/app/static/frontend`), gunicorn `-w 4` uvicorn workers, `main.py` serves SPA when `STATIC_FILES_DIR` is set and absolute/existing; CORS origins come from `CORS_ORIGINS` settings (no wildcard in code). `render.yaml` provisions web service + free Postgres.

### 1.2 Full API surface (verified via OpenAPI)

```
POST   /api/v1/auth/register          POST   /api/v1/auth/login            GET /api/v1/auth/me
POST   /api/v1/resumes                GET    /api/v1/resumes
GET    /api/v1/resumes/{resume_id}    DELETE /api/v1/resumes/{resume_id}
POST   /api/v1/job-descriptions       GET    /api/v1/job-descriptions
GET    /api/v1/job-descriptions/{id}  DELETE /api/v1/job-descriptions/{id}
POST   /api/v1/job-descriptions/from-url
POST   /api/v1/job-descriptions/match
POST   /api/v1/generate
POST   /api/v1/applications           GET    /api/v1/applications
GET    /api/v1/applications/{app_id}  PATCH  /api/v1/applications/{app_id}
DELETE /api/v1/applications/{app_id}
POST   /api/v1/job-search             GET    /api/v1/job-search/saved
POST   /api/v1/job-search/{id}/import
GET    /api/v1/dashboard/stats        GET    /api/v1/health
```

### 1.3 Database models (current)

| Model | Table | Notable columns / issues |
|---|---|---|
| `User` | `users` | UUID PK, email unique, bcrypt hash, `is_active` |
| `Resume` | `resumes` | `raw_text` Text, `parsed_data` JSONB, `is_active` |
| `ResumeChunk` | `resume_chunks` | `chunk_type`, `metadata` JSONB, `embedding` **ARRAY(Float)** (pgvector unused), nullable |
| `JobDescription` | `job_descriptions` | `parsed_data` JSONB (role, must/nice skills, responsibilities, seniority) |
| `MatchScore` | `match_scores` | `overall_score` Float 0–100, matched/missing JSONB |
| `Application` | `applications` | status PG **Enum**(`saved/applied/interview/offer/rejected`), FKs to JD + resume |
| `JobSearchResult` | `job_search_results` | `source`, salary range, `imported` flag; **no dedup constraint** |

---

## 2. What already works (KEEP — do not rewrite)

All verified by import/build inspection plus the earlier behavioral verification session; DB-dependent flows not re-run end-to-end in this audit (no local Postgres).

1. **Auth stack** — register/login/me, bcrypt hashing, JWT issuance/validation, `get_current_user` dependency, global 401 handling in frontend.
2. **Resume ingestion pipeline** — upload (PDF/DOCX/TXT, ≤10 MB, extension allow-list), text extraction (PyPDF2/python-docx), regex section parsing, skill extraction, typed chunking, embedding, chunk storage with counts.
3. **JD ingestion** — paste text or URL fetch (httpx + BeautifulSoup), `parse_jd` → role/must-have/nice-to-have/responsibilities/seniority, stored as JSONB.
4. **Match scoring** — 60% must-have keyword coverage + 40% mean top-5 cosine embedding similarity, persisted `MatchScore`, ownership-checked endpoint.
5. **RAG generation with citation enforcement** — top-8 chunk retrieval, `[SOURCE: N]` citation extraction and validation back to chunk IDs; three content types (cover letter, summary, bullets).
6. **Application tracker** — CRUD with ownership checks, status enum, Kanban frontend.
7. **Job search** — Adzuna (keyed) + RemoteOK (keyless), save results, import into JD table.
8. **Dashboard analytics** — status counts, weekly applications, avg match, response rate (denominator excludes `saved`), skill-gap frequency trends.
9. **Frontend shell** — routing, protected routes, Layout, 6 feature pages, consistent visual language (to be preserved per product constraints).
10. **Deploy path** — dev compose (pgvector image, hot-reload), production single-service image, Render blueprint, `/api/v1/health` for probes.
11. **Recent correctness fixes already in tree** (commit `2d282b8`): ownership checks on `POST /applications` and `POST /job-descriptions/match`; correct response-rate denominator; per-JD counting in skill-gap loop; no wildcard CORS in production; frontend dev baseURL single `/api/v1`.

**Explicitly DO NOT change:** the `core/` (config/database/security/deps) patterns, model naming and table names, existing route shapes and response schemas (frontend depends on them), the frontend visual language and page structure, the resume chunking/embedding approach, matching formula, or Docker topology. The target spec is additive: this repo becomes the "brain", not a rewrite.

---

## 3. What is partially implemented

| Area | State | Gap vs target |
|---|---|---|
| LLM integration | Works via Anthropic/OpenAI only | No `LLMProvider` abstraction; no Ollama; model names hard-coded; no timeout; clients re-created per request; provider chosen implicitly by which key is set |
| Vector search | Chunks embedded; cosine in Python | Embeddings in `ARRAY(Float)`, similarity loads **all** chunks per resume into memory; no pgvector index; no similarity *query* in SQL |
| Job matching | Keyword+embedding score | No required-vs-preferred distinction surfaced (both exist in `parsed_data` but score uses must-have only), no experience/location/education compatibility, no `concerns`/`recommendation` fields |
| JD ingestion | URL fetch + parse | **No SSRF protection** — fetches arbitrary user-supplied URLs server-side (internal network reachable) |
| Job search | Two sources, saved results | No cross-source deduplication; every search inserts rows (table grows with duplicates); no normalized job model |
| Migrations | Alembic fully wired, zero revisions | All schema changes will need migrations from a clean baseline; `create_all` and Alembic can drift |
| Resume structure | `parsed_data` JSONB with skills/sections | Not a *candidate profile*: no contact info, work authorization, notice period, salary, links, or per-field authority |
| Tests | None (pytest installed only) | No backend tests, no frontend tests, no fixtures |
| README | Accurate for what exists | Must gain IMPLEMENTED/PARTIAL/PLANNED split as milestones land |

---

## 4. What is missing (mapped to the FastApply-style target)

1. **LLM provider abstraction + local Ollama provider** (`backend/app/ai/providers/*`, `GET /api/v1/ai/health`, `POST /api/v1/ai/chat`, `POST /api/v1/ai/generate-json`).
2. **Candidate profile** model + `GET/PATCH /api/v1/profile` (authoritative personal data the LLM may never invent).
3. **Application question memory** (`application_questions` with normalized question, answer, source, confidence, embedding) + semantic retrieval for answer reuse.
4. **Answer engine** `POST /api/v1/agent/answer` with structured output `{answer, confidence, source[], requires_review}` and **field policies** (`PROFILE_ONLY`, `PROFILE_OR_MEMORY`, `RESUME_REQUIRED`, `LLM_GENERATED`, `USER_CONFIRMATION_REQUIRED`).
5. **Anti-hallucination validation layer** — policy enforcement, confidence gating, sensitive-question confirmation (work auth, salary, sponsorship, demographics, criminal history, relocation, travel).
6. **Chrome extension (MV3)** — form detection/extraction/normalization, deterministic autofill from profile, confidence display, edit/accept/skip review, pause-before-submit.
7. **Browser action schema** — strict Pydantic action whitelist (`FILL, SELECT, CHECK, UNCHECK, CLICK, SCROLL, WAIT, EXTRACT, UPLOAD, NEXT_PAGE, STOP`); LLM output never executes arbitrary JS/URLs.
8. **ATS adapters** (`backend/app/ats/`: generic → greenhouse → lever → workday) with detect/extract/fill/next-page/submission-detection interface.
9. **Multi-page agent state machine** (`backend/app/agent/`: state, planner, executor, validator, memory) with persisted state and `READY_FOR_REVIEW` terminal state before `USER_SUBMISSION`.
10. **Review UI** — per-answer question/answer/confidence/source with edit/accept/skip; agent dashboard with AI status, progress, field counts.
11. **Playwright harness + HTML fixtures** under `tests/browser/fixtures/` for deterministic browser testing without hitting real job boards.
12. **Observability** — agent logs (state transitions, actions, success/failure, retry counts) without logging sensitive content.
13. **Job queue (later, M10)** — Redis only once single-application flow works.
14. **Resume selection flow** — multi-resume match → user confirmation → upload (extension side).

---

## 5. Files that should be reused as-is (highest-leverage assets)

- `backend/app/services/resume_service.py` — `extract_text`, `parse_resume`, `chunk_resume`, `embed_texts`, `embed_query`, lazy model singleton. The answer engine's retrieval layer builds directly on this.
- `backend/app/services/matching_service.py` — `cosine_similarity`, `compute_match_score`; reused by resume-selection and JD matching.
- `backend/app/services/jd_service.py` — `parse_jd`, `fetch_jd_from_url` (fetch needs an SSRF guard; parser itself is solid).
- `backend/app/services/generation_service.py` — retrieval + citation-extraction logic and prompt structure are the seed for `ai/agents/answer_agent.py`; only the `_call_llm*` block gets replaced by the provider abstraction.
- `backend/app/core/*` — settings, DB, security, deps all sound; extend `config.py` with `LLM_PROVIDER`/`OLLAMA_*` fields rather than restructuring.
- `backend/app/models/models.py` + `schemas/schemas.py` — extend, don't duplicate (e.g., there is already a User/Resume/JD/Application; do **not** create parallel Job/ATSSession tables where existing ones suffice).
- `backend/alembic/env.py` — already imports all models into `Base.metadata`; first revision just works.
- Frontend: `services/api.js`, `contexts/AuthContext.jsx`, `App.jsx` routing, `components/Layout.jsx` — new pages (Agent, Profile, Review) plug into this unchanged.
- Infra: both compose files, `Dockerfile.production`, `render.yaml` — only env-var additions needed.

## 6. Files/targets that need refactoring (incremental, not rewrite)

| Target | Refactor |
|---|---|
| `generation_service._call_llm*` | Replace ~40 lines with `ai/providers/` strategy; keep identical call signature so `generate_content` changes by one line |
| `core/database.py` | Introduce Alembic as source of truth (baseline revision), keep `create_all` for dev-only bootstrap |
| `core/database.get_db` | Stop committing on requests that performed no writes (commit only when dirty) — removes needless write transactions on GETs |
| `ResumeChunk.embedding` | Migrate `ARRAY(Float)` → `pgvector.VECTOR(384)` with an ivfflat/hnsw index; backfill conversion in the same migration |
| `job_search_service` / `job_search.py` | Add dedup on (user, url) or (title, company, source) before insert; normalized job model |
| `jd_service.fetch_jd_from_url` | URL validation: allow only http(s), resolve+block private/loopback/link-local ranges, size+content-type caps |
| `resumes.py` upload | sniff content bytes (magic numbers) instead of trusting filename extension; MIME validation |
| Embedding model load | Eager-load in lifespan (or background thread) so first request doesn't pay ~seconds of cold start; consider preloading once per worker |
| `dashboard.py`, `applications.py` | N+1 loops → joined loads (functional only; not urgent) |
| `config.py` | Add `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `LLM_TIMEOUT_SECONDS`; require non-default `SECRET_KEY` when `DEBUG=false` |

## 7. Defects and risks found during audit (new, not yet fixed)

1. **`.env.example` first line is `[TEMPLATE]`** — not a valid KEY=VALUE. `pydantic-settings` with `extra=ignore` happens to tolerate it, but it is junk that should be removed (one-line fix, M1).
2. **Dev compose double-prefix bug:** `docker-compose.yml` sets `VITE_API_URL=http://localhost:8000/api/v1`, and `api.js` appends `/api/v1` again → in Docker dev the frontend calls `http://localhost:8000/api/v1/api/v1/...`. Breaks API calls in the dev container path only (bare-metal dev and production are fine).
3. **`render.yaml` sets `CORS_ORIGINS: '["*"]'`** while CORS middleware uses `allow_credentials=True` — browsers reject `Access-Control-Allow-Origin: *` with credentials; also contradicts the hardened production default. Blueprint should not ship a wildcard.
4. **SSRF exposure** via `POST /job-descriptions` (URL fetch) — user can make the server GET internal addresses. Highest-priority security fix alongside M1.
5. **`get_db` commits on every request**, including read-only GETs — unnecessary write transactions/locks under load.
6. **No LLM call timeout** and per-request client construction — a hung Anthropic/OpenAI call stalls a worker; with Ollama (slow local inference) this becomes a real availability issue → provider abstraction must include timeouts and shared clients.
7. **Lazy embedding model load in request path** — first resume upload/query pays model-load latency; with 4 gunicorn workers each loads its own copy (~memory cost).
8. **`python-jose` 3.3.0** has published CVEs (e.g., CVE-2024-33663/33664); fine short-term, but plan a swap to PyJWT when auth is next touched.
9. **`HTTPBearer` returns 403 (not 401) for missing tokens** (auto_error default); frontend interceptor only reacts to 401 → minor UX inconsistency.
10. **No tests at all** — biggest process risk as the system grows (addressed in testing strategy below).
11. **Secrets defaults:** `SECRET_KEY="change-me-in-production"` works silently; should fail fast in production mode.

---

## 8. Database changes required (with migrations — never manual)

Existing tables are kept. Required additions/changes in this order:

1. **Baseline Alembic revision** capturing the current 7-table schema (so pgvector/column changes are proper migrations, and `create_all` stops being the source of truth).
2. **`ALTER resume_chunks.embedding` → `vector(384)`** + ivfflat/hnsw index on `(embedding vector_cosine_ops)`; backfill converts float arrays. (pgvector extension already available via `pgvector/pgvector:pg16` image; `pgvector` Python package already in requirements.)
3. **New table `profiles`** (1:1 with `users`): full_name, email, phone, location, links (github/linkedin/portfolio), education JSONB, experience JSONB, skills JSONB, projects JSONB, work_authorization JSONB, notice_period, salary_expectation, willing_to_relocate, preferred_locations, created_at/updated_at.
4. **New table `application_questions`**: id, user_id, question, normalized_question, answer, embedding `vector(384)`, source (user/profile/memory/llm), confidence, context (job/company), created_at/updated_at, index on (user_id, normalized_question) + vector index.
5. **New tables for the agent (M7):** `agent_sessions` (job url, ats type, state machine state, resume_id selection, timestamps), `agent_actions` (session_id, action type from the whitelist, payload JSONB, result, error, created_at) — doubles as the observability log.
6. Optional (M10+, only if queue lands): queue/job-state columns or tables — deliberately deferred.
7. Extension of `Application` enum is **not** needed initially (`saved` covers pre-submission review states; agent session state lives in `agent_sessions`).

## 9. API changes required (additive; existing 23 operations unchanged)

```
GET    /api/v1/ai/health            # provider + ollama reachability (frontend "Local AI: Connected/Offline")
POST   /api/v1/ai/chat              # generic provider chat (debug/utility)
POST   /api/v1/ai/generate-json     # structured JSON generation with schema validation
GET    /api/v1/profile              PATCH /api/v1/profile
GET    /api/v1/memory/search?q=     POST /api/v1/memory/answers       PATCH /api/v1/memory/answers/{id}
POST   /api/v1/agent/answer         # the answer engine: question+JD+field_type → {answer, confidence, source[], requires_review}
POST   /api/v1/agent/sessions       GET  /api/v1/agent/sessions/{id}  POST .../actions   (M7)
GET    /api/v1/ats/detect           # (M6) ATS detection from page hints
```

All new routers mounted under the existing `api_router` (`/api/v1`) with the existing `get_current_user` dependency; all request/response shapes as Pydantic v2 schemas in `schemas/schemas.py` or new `schemas/ai.py` / `schemas/agent.py` to keep files small.

## 10. Chrome extension requirements

- MV3; `manifest.json` with content scripts on application pages, background service worker, popup + options pages; no secrets in the extension — it authenticates to `http://localhost:8000` with the user's JWT (entered in options, stored in `chrome.storage.local`).
- Content pipeline: `form-detector.js` (find forms/fields, incl. Shadow DOM best-effort) → `field-mapper.js` (normalize to the agreed field schema: id, label, name, placeholder, aria-label, type, options, required, selector, section) → `autofill.js` (executes **only** backend-approved action types; native setters + input/change events for React/ATS compatibility).
- Popup: connect status, detected field count, fill buttons, review panel (answer, confidence %, sources, edit/accept/skip), explicit "Ready for review" gate before any submission.
- Deterministic fields (first/last name, email, phone, LinkedIn, GitHub, portfolio, location) resolve locally from `GET /api/v1/profile` — **never** sent to the LLM.
- Milestone order: detect/extract (M3) → deterministic autofill (M4) → AI answers with review (M5/M8). Tested against local HTML fixtures, not live job boards.

## 11. Ollama integration requirements

- `backend/app/ai/providers/base.py`: `class LLMProvider` with `async generate(...)`, `async generate_json(...)`, `async health_check()`; providers: `ollama.py`, `openai.py`, `anthropic.py`; factory selects on `LLM_PROVIDER` env (`ollama` requires **no API key**).
- Config additions to `config.py` + `.env.example` (and compose env passthroughs): `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen3:8b` (never hard-coded), `LLM_TIMEOUT_SECONDS` (generous default for local hardware).
- Ollama provider speaks its native HTTP API (`/api/generate`, `/api/chat`, `/api/tags` for health) with `format=json` for structured calls; clear typed error when Ollama is unreachable ("Local AI: Offline" in frontend).
- All agent-controlling LLM output must parse through `generate_json` into Pydantic models; parse failure → retry-with-error prompt once → `requires_review` fallback, never raw prose into the executor.
- Cloud providers (OpenAI/Anthropic) remain available via the same interface; `generation_service` migrates onto it without changing its external behavior.
- Tests mock the provider interface entirely — the suite never requires a running Ollama.

## 12. Security concerns (consolidated)

1. SSRF in `fetch_jd_from_url` (fix in M1 window: URL allow-list logic, private-range blocking, response size cap).
2. `CORS_ORIGINS='["*"]'` shipped in render.yaml with credentials — remove wildcard from blueprint.
3. `SECRET_KEY` silent default; must fail fast when `DEBUG=false`.
4. Extension is a new attack surface: backend must validate every action against the strict whitelist; extension must never `eval`/inject arbitrary JS; CORS for the extension origin must be explicit, and `/api/v1/ai/*` + `/api/v1/agent/*` stay authenticated.
5. Resume/profile/question memory = highly sensitive PII: keep auth on every route, no PII in logs, no PII in LLM prompts beyond what's needed for the answer, file uploads re-validated by content (magic bytes) not just extension.
6. LLM prompt-injection: JD text fetched from the web is untrusted input to the answer engine — treat it as data, never as instructions; action schema validation is the backstop.
7. `python-jose` CVEs → migrate to PyJWT opportunistically.
8. Rate limiting on generation/answer endpoints (local LLM is also a DoS target) — lightweight in-process limiter first, no Redis needed initially.
9. `python-multipart`/upload size already capped at 10 MB — keep; add per-user storage accounting later.

## 13. Testing strategy

Current state: **zero tests** (pytest 9.1.1 installed, unused; frontend has no test runner). Target, introduced milestone-by-milestone so every milestone ships with tests:

- **Backend (pytest + pytest-asyncio):** unit tests for pure logic (parsing, chunking, matching, action validation, field policies, question normalization); API tests via `httpx.ASGITransport` with dependency-overridden DB (the pattern already proven during the earlier fix-verification session); provider tests with a fake `LLMProvider` plus contract tests per provider (skipped unless the real service is reachable); retrieval tests against fixtures. DB integration tests run when a Postgres is available (dev compose), skipped cleanly otherwise.
- **LLM never required for the suite:** all answer-engine tests use mocked provider JSON responses.
- **Browser/extension (M3–M9):** HTML fixtures under `tests/browser/fixtures/` (`simple_form.html`, `greenhouse_form.html`, `lever_form.html`, `multi_page_form.html`, `custom_dropdown.html`, `file_upload.html`, `unknown_question_form.html`); Playwright loads fixtures, form-detector/field-mapper logic tested in-page, autofill verified against fixtures; screenshots on failure.
- **Frontend:** add vitest + React Testing Library when the first UI with real logic (review screen) lands; keep oxlint green.
- **CI-ready gate per milestone:** `npm run build && npm run lint` + `pytest` + backend import check.

## 14. Exact implementation plan (milestones, additive only)

| # | Milestone | Touches | Reuses | Ships |
|---|---|---|---|---|
| M0 | Audit (this document) | docs only | — | ✅ this file |
| M1 | **Local LLM** | new `app/ai/providers/{base,ollama,openai,anthropic}.py`; refactor `_call_llm` onto provider factory; config + `.env.example` additions (+ remove `[TEMPLATE]` line, fix compose `VITE_API_URL`); `GET /ai/health`, `POST /ai/chat`, `POST /ai/generate-json`; SSRF guard in `fetch_jd_from_url`; fail-fast SECRET_KEY in prod | generation_service retrieval/citations; core config | Ollama→FastAPI→validated JSON; pytest for providers/factory/endpoints with mocked Ollama |
| M2 | **Profile + memory** | `profiles` + `application_questions` tables (Alembic baseline first, pgvector migration); `app/ai/retrieval/{profile_retriever,resume_retriever,question_memory}.py`; profile + memory routers; question normalization | resume_service embeddings; cosine_similarity | question → embed → similar prior answers → answer context; tests for normalization + retrieval |
| M3 | **Chrome extension skeleton** | new top-level `extension/` (MV3, detector, mapper, popup, options, background); fixtures under `tests/browser/fixtures/` | `/auth/login` for JWT; `/profile` | extension detects/extracts fields from local fixture pages; detector logic unit-tested |
| M4 | **Deterministic autofill** | extension `autofill.js` + profile field mapping; backend policy map (PROFILE_ONLY fields) | `GET /api/v1/profile` | profile fields auto-fill without any LLM; tested on fixtures |
| M5 | **AI answer engine** | `app/ai/agents/answer_agent.py` + `prompts/`; `POST /agent/answer`; field-policy engine (`PROFILE_ONLY…USER_CONFIRMATION_REQUIRED`); confidence gating | M2 retrieval; M1 provider | unknown question → memory/profile/resume/JD → grounded JSON answer with confidence/sources/review flag; mocked-LLM tests |
| M6 | **ATS adapters** | `app/ats/{base,workday,greenhouse,lever,ashby,generic}.py` + detection endpoint | extension field schema | ATS detection + adapter-specific extraction quirks; only claim support proven by fixtures |
| M7 | **Multi-page agent** | `app/agent/{state,planner,executor,validator,memory}.py`; `agent_sessions`/`agent_actions` tables; browser action schema (Pydantic whitelist) | matching_service; answer engine | DISCOVER→…→READY_FOR_REVIEW state machine with persisted, crash-recoverable state; never auto-submits |
| M8 | **Review UI** | frontend: Agent page (status, progress, field counts, review cards edit/accept/skip), Profile editor, memory suggestions | existing Layout/pages/visual language | human-in-the-loop review gate; agent dashboard |
| M9 | **Playwright testing** | `browser/` harness (`manager, page_state, selectors, actions, screenshots`); CI-style suite over all fixtures | extension content scripts | automated end-to-end over fixtures, screenshots on failure |
| M10 | **Job queue (only if needed)** | Redis worker for queued applications | agent state machine | queue states JOB_DISCOVERED→…→TRACKING |
| M11 | **Optional LangGraph** | evaluation only | — | adopt only if it beats explicit state management |
| M12 | **Autonomous mode** | opt-in flag, defaults OFF | everything | queue → agent → review → submit, exceptions surfaced to user; human-review remains default |

**Definition of done for the MVP** (per spec §39): Ollama + Postgres + FastAPI up; extension loaded; fixture application page open; form detected; profile fields auto-filled; unknown question answered by grounded local LLM; answer displayed with confidence + editable; accepted answers filled; next-page navigation; stop before submission; application + question/answer persisted in Postgres for future reuse.

**Commits:** one feature per commit (`feat: add local Ollama provider`, `feat: add candidate profile memory`, `feat: add Chrome form detector`, …), tests included per milestone; README updated only after each feature is implemented and verified, with IMPLEMENTED/PARTIAL/PLANNED separation.

---

## 15. Audit conclusion

The repository is a healthy, working **job-application workspace** and a strong base: auth, resume RAG, JD parsing, matching, tracking, search, dashboard, and a working deploy path all function and none need rewriting. The gap to the FastApply-style target is concentrated in five additions — provider abstraction with Ollama, profile + question memory with real pgvector retrieval, the Chrome extension, the answer engine with anti-hallucination policies, and the multi-page agent with human review — all of which are additive on top of the existing architecture. Two small latent bugs (`[TEMPLATE]` in `.env.example`, dev-compose `VITE_API_URL` double prefix) and one security gap (SSRF in JD URL fetch) should ride along with M1.

**Recommendation:** approve this audit and proceed to Milestone 1 (local LLM provider abstraction + Ollama + AI endpoints + the three small fixes above).
