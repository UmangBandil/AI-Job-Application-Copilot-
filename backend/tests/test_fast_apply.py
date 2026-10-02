"""Tests for the M6 Fast Apply batch analysis endpoint.

One analyze request per form: confidence-gated classification buckets,
job upsert/dedup, duplicate-application detection, generation caps, and
warnings. No live LLM, no database — providers are fakes patched at the
answer_agent module boundary, sessions are routing fakes, embeddings are
stubbed, and DNS resolution is faked so no network is touched.
"""

import socket
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.main import app


# ── Fakes ─────────────────────────────────────────────────────────────


class FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows


class FastApplyFakeSession:
    """Routes statements by table name; supports the M6 query mix.

    Note the check order: "resume_chunks" before "resumes" (the chunk query
    joins resumes) and "application_questions" before "applications" (the
    memory query contains the other as a substring).
    """

    def __init__(
        self,
        profile=None,
        job_by_url=None,
        job_by_company_title=None,
        application=None,
        has_resume=True,
        chunk_rows=None,
    ):
        self.profile = profile
        self.job_by_url = job_by_url
        self.job_by_company_title = job_by_company_title
        self.application = application
        self.has_resume = has_resume
        self.chunk_rows = chunk_rows or []
        self.added = []
        self.flushed = 0

    async def execute(self, stmt):
        sql = str(stmt)
        if "job_descriptions" in sql:
            if "lower" in sql:  # company+title dedup query
                return FakeResult(scalar=self.job_by_company_title)
            return FakeResult(scalar=self.job_by_url)
        if "resume_chunks" in sql:
            return FakeResult(rows=self.chunk_rows)
        if "application_questions" in sql:
            if "<=>" in sql:  # pgvector semantic memory search
                return FakeResult(rows=[])
            return FakeResult(scalar=None)
        if "applications" in sql:
            return FakeResult(scalar=self.application)
        if "resumes" in sql:
            return FakeResult(scalar=uuid.uuid4() if self.has_resume else None)
        if "profiles" in sql:
            return FakeResult(scalar=self.profile)
        return FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    async def refresh(self, obj):
        pass


class FakeUser:
    id = uuid.uuid4()
    email = "t@example.com"
    is_active = True


class FakeProvider:
    name = "fake"

    def __init__(self, payloads=None):
        self.payloads = list(payloads or [])
        self.calls = 0

    async def generate(self, prompt, system="", max_tokens=2000):
        return "FAKE"

    async def generate_json(self, prompt, system="", max_tokens=2000):
        self.calls += 1
        if self.payloads:
            item = self.payloads.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {"answer": "stub", "confidence": 0.9, "notes": ""}

    async def health_check(self):
        return {"provider": "fake", "connected": True}


class NeverCalledProvider(FakeProvider):
    async def generate_json(self, prompt, system="", max_tokens=2000):
        raise AssertionError("LLM must not be called for this field")


# ── Builders ──────────────────────────────────────────────────────────


def _profile(**kw):
    from app.models import Profile

    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(), user_id=FakeUser.id,
        full_name="", email="", phone="", location="",
        website="", linkedin_url="", github_url="", portfolio_url="",
        education=[], experience=[], skills=[], projects=[],
        work_authorization={}, notice_period="", salary_expectation="",
        willing_to_relocate=None, preferred_locations=[],
        created_at=now, updated_at=now,
    )
    defaults.update(kw)
    return Profile(**defaults)


def _job(**kw):
    from app.models import JobDescription

    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(), user_id=FakeUser.id, title="Software Engineer",
        company="Google", raw_text="", source_url="https://jobs.example.com/apply/123",
        parsed_data={}, created_at=now,
    )
    defaults.update(kw)
    return JobDescription(**defaults)


def _application(status="applied", **kw):
    from app.models import Application

    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(), user_id=FakeUser.id, job_description_id=uuid.uuid4(),
        resume_id=uuid.uuid4(), status=status, match_score=None,
        cover_letter="", tailored_resume="", notes="",
        follow_up_date=None, created_at=now, updated_at=now,
    )
    defaults.update(kw)
    return Application(**defaults)


def _field(field_id, label="", type="text", options=None, required=False, selector=None, **kw):
    body = {
        "field_id": field_id,
        "selector": selector or f"#{field_id}",
        "label": label,
        "type": type,
        "options": options or [],
        "required": required,
    }
    body.update(kw)
    return body


def _analyze_payload(fields, **kw):
    body = {
        "page_url": "https://jobs.example.com/apply/123",
        "job_title": "Software Engineer",
        "company": "Google",
        "fields": fields,
    }
    body.update(kw)
    return body


# ── Environment ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fast_env(monkeypatch):
    """Stub embeddings, fake DNS so URL validation never touches network."""
    import app.ai.agents.answer_agent as aa
    import app.ai.retrieval.question_memory as qm

    fake_vec = [0.1] * 384
    monkeypatch.setattr(aa, "embed_query", lambda q: fake_vec)
    monkeypatch.setattr(qm, "embed_query", lambda q: fake_vec)

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr("app.services.url_guard.socket.getaddrinfo", fake_getaddrinfo)


def _setup_overrides(db):
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser()


@pytest.fixture()
def cleanup():
    yield
    app.dependency_overrides.clear()


async def _post(path, json_body, monkeypatch=None, provider=None):
    if monkeypatch is not None and provider is not None:
        import app.ai.agents.answer_agent as aa

        monkeypatch.setattr(aa, "get_llm_provider", lambda: provider)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=json_body)


# ── Classification confidence (Phase 3/4) ─────────────────────────────


def test_classification_confidence_levels():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    p, _, c = classify_question("Do you require visa sponsorship?")
    assert p is AnswerPolicy.USER_CONFIRMATION_REQUIRED
    assert c == 1.0

    p, _, c = classify_question("What is your email address?")
    assert p is AnswerPolicy.PROFILE_ONLY
    assert c == 0.95

    p, _, c = classify_question("How many years of experience do you have?")
    assert p is AnswerPolicy.PROFILE_OR_MEMORY
    assert c == 0.90

    p, _, c = classify_question("Preferred work style?", field_type="select")
    assert p is AnswerPolicy.PROFILE_OR_MEMORY
    assert c == 0.85

    p, _, c = classify_question("Why do you want to work here?", field_type="textarea")
    assert p is AnswerPolicy.LLM_GENERATED
    assert c == 0.90

    p, _, c = classify_question("Current employer")
    assert p is AnswerPolicy.LLM_GENERATED
    assert c == 0.75


def test_blank_or_useless_labels_are_unknown_with_zero_confidence():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    for text in ("", "   ", "12345", "***"):
        policy, reason, confidence = classify_question(text)
        assert policy is AnswerPolicy.UNKNOWN
        assert confidence == 0.0
        assert reason


async def test_unknown_question_never_reaches_llm(cleanup, monkeypatch):
    _setup_overrides(FastApplyFakeSession(profile=_profile()))
    resp = await _post(
        "/api/v1/agent/answer",
        {"question": "  ", "field_type": "text"},
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy"] == "unknown"
    assert body["requires_review"] is True
    assert body["answer"] is None
    assert body["fill_action"] is None


# ── Analyze: happy path ───────────────────────────────────────────────


async def test_analyze_happy_path(cleanup, monkeypatch):
    db = FastApplyFakeSession(
        profile=_profile(full_name="Umang Bandil", email="umang@example.com"),
        has_resume=True,
    )
    _setup_overrides(db)
    provider = FakeProvider([
        {"answer": "I want to build great products.", "confidence": 0.93, "notes": ""},
    ])
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([
            _field("f-first", "First Name"),
            _field("f-email", "Email Address", type="email"),
            _field("f-why", "Why do you want to work here?", type="textarea"),
            _field("f-auth", "Are you legally authorized to work in the US?", type="radio"),
            _field("f-blank", ""),
        ]),
        monkeypatch,
        provider,
    )
    assert resp.status_code == 200
    body = resp.json()

    # Job identity: created fresh from the payload.
    assert body["job"]["created"] is True
    assert body["job"]["title"] == "Software Engineer"
    assert body["job"]["source_url"] == "https://jobs.example.com/apply/123"

    # Buckets: 2 profile fills + 1 high-confidence AI answer → safe.
    assert len(body["safe_actions"]) == 3
    fill_values = {a["field_id"]: a["value"] for a in body["safe_actions"] if a["action"] == "FILL"}
    assert fill_values["f-first"] == "Umang"
    assert fill_values["f-email"] == "umang@example.com"
    assert fill_values["f-why"] == "I want to build great products."

    # Sensitive field blocked; blank field in review; nothing auto-filled.
    assert len(body["blocked_actions"]) == 1
    assert body["blocked_actions"][0]["field_id"] == "f-auth"
    assert len(body["review_actions"]) == 1
    assert body["review_actions"][0]["field_id"] == "f-blank"
    assert "cannot classify" in body["review_actions"][0]["reason"]

    # Generated answer carries provenance.
    gen = body["generated_answers"]
    assert len(gen) == 1
    assert gen[0]["field_id"] == "f-why"
    assert gen[0]["requires_review"] is False
    assert "llm" in gen[0]["sources"]
    assert "profile" in gen[0]["sources"]

    # Warnings are visible: unknown field + sensitive fields + no JD text.
    warnings = " ".join(body["warnings"])
    assert "could not be classified" in warnings
    assert "sensitive" in warnings
    assert "No job description text" in warnings

    # Per-field classifications carry confidence.
    by_id = {f["field_id"]: f for f in body["fields"]}
    assert by_id["f-email"]["confidence"] == 0.95
    assert by_id["f-why"]["confidence"] == 0.90
    assert by_id["f-blank"]["policy"] == "unknown"

    # Summary counts line up.
    assert body["summary"]["fields_detected"] == 5
    assert body["summary"]["safe_actions"] == 3
    assert body["summary"]["blocked_actions"] == 1


async def test_analyze_profile_missing_value_goes_to_review(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(full_name=""), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([_field("f-first", "First Name")]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["safe_actions"] == []
    assert len(body["review_actions"]) == 1
    assert "profile field 'first_name' is empty" in body["review_actions"][0]["reason"]


async def test_choice_field_confidence_band_fills_only_after_review(cleanup, monkeypatch):
    """0.70–0.89 fields are fillable, but only after the human sees them."""
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    provider = FakeProvider([{"answer": "Hybrid", "confidence": 0.95, "notes": ""}])
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([
            _field(
                "f-setup", "Preferred work setup?", type="select",
                options=[{"value": "1", "label": "Remote"}, {"value": "2", "label": "Hybrid"}],
            ),
        ]),
        monkeypatch,
        provider,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["safe_actions"] == []  # 0.85 < 0.90 — never auto-fill
    review = body["review_actions"]
    assert len(review) == 1
    assert review[0]["field_id"] == "f-setup"
    assert review[0]["fill_action"]["action"] == "SELECT"
    assert review[0]["fill_action"]["option_value"] == "2"
    assert len(body["generated_answers"]) == 1


# ── Job upsert / dedup (Phase 12) ─────────────────────────────────────


async def test_analyze_creates_job_description(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([], job_description="Build great software."),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job"]["created"] is True
    assert len(db.added) == 1
    created = db.added[0]
    assert created.source_url == "https://jobs.example.com/apply/123"
    assert created.title == "Software Engineer"
    assert created.company == "Google"
    assert created.raw_text == "Build great software."
    assert "No job description text" not in " ".join(body["warnings"])


async def test_analyze_dedups_job_by_source_url(cleanup, monkeypatch):
    existing = _job()
    db = FastApplyFakeSession(profile=_profile(), job_by_url=existing, has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job"]["created"] is False
    assert body["job"]["id"] == str(existing.id)
    assert db.added == []  # no duplicate JobDescription staged


async def test_analyze_dedups_job_by_company_and_title(cleanup, monkeypatch):
    existing = _job(source_url="https://careers.example.com/g/swe-1")
    db = FastApplyFakeSession(
        profile=_profile(), job_by_url=None, job_by_company_title=existing, has_resume=True,
    )
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([], company="google", job_title="software engineer"),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job"]["created"] is False
    assert body["job"]["id"] == str(existing.id)
    assert db.added == []


async def test_duplicate_application_detected_with_date(cleanup, monkeypatch):
    applied_on = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    existing_job = _job()
    prior = _application(status="applied", job_description_id=existing_job.id, created_at=applied_on)
    db = FastApplyFakeSession(
        profile=_profile(), job_by_url=existing_job, application=prior, has_resume=True,
    )
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["already_applied"] is not None
    assert body["already_applied"]["application_id"] == str(prior.id)
    assert body["already_applied"]["status"] == "applied"
    assert "2026-09-15" in body["already_applied"]["applied_at"]
    assert any("already applied" in w for w in body["warnings"])


async def test_no_prior_application_means_not_applied(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["already_applied"] is None
    assert not any("already applied" in w for w in body["warnings"])


# ── Generation cap + warnings (Phase 8/19) ────────────────────────────


async def test_max_generated_cap_defers_rest_to_review(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    provider = FakeProvider([
        {"answer": "First answer.", "confidence": 0.9, "notes": ""},
        {"answer": "Second answer.", "confidence": 0.9, "notes": ""},
        {"answer": "Third answer.", "confidence": 0.9, "notes": ""},
    ])
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([
            _field("f-q1", "Why do you want to work here?", type="textarea"),
            _field("f-q2", "Describe a relevant project.", type="textarea"),
            _field("f-q3", "Why should we hire you?", type="textarea"),
        ], max_generated=1),
        monkeypatch,
        provider,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert provider.calls == 1  # cap respected — no extra LLM calls
    assert len(body["generated_answers"]) == 1
    deferred = [r for r in body["review_actions"] if "generation limit" in r["reason"]]
    assert len(deferred) == 2
    assert any("deferred (AI generation limit of 1)" in w for w in body["warnings"])


async def test_low_confidence_llm_answer_shown_but_not_auto_filled(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    provider = FakeProvider([{"answer": "A guess.", "confidence": 0.3, "notes": ""}])
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([_field("f-q", "Why do you want to work here?", type="textarea")]),
        monkeypatch,
        provider,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["safe_actions"] == []
    gen = body["generated_answers"][0]
    assert gen["answer"] == "A guess."
    assert gen["requires_review"] is True
    assert gen["fill_action"] is None


async def test_no_resume_warning(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=False)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    assert any("No resume on file" in w for w in resp.json()["warnings"])


# ── Hard safety buckets (Phases 3/10/21) ──────────────────────────────


async def test_sensitive_fields_are_blocked_not_answered(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([
            _field("f-visa", "Do you require visa sponsorship?"),
            _field("f-salary", "What is your expected salary?"),
            _field("f-gender", "What is your gender?"),
            _field("f-travel", "Are you able to travel 50%?"),
        ]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {b["field_id"] for b in body["blocked_actions"]} == {"f-visa", "f-salary", "f-gender", "f-travel"}
    assert body["safe_actions"] == []
    assert body["generated_answers"] == []


async def test_password_fields_never_filled(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([_field("f-pass", "Create a password", type="password")]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["safe_actions"] == []
    assert body["blocked_actions"][0]["reason"] == "password fields are never filled"


async def test_field_without_selector_is_never_filled(cleanup, monkeypatch):
    """No CSS selector → nothing can be filled reliably; surface it."""
    db = FastApplyFakeSession(profile=_profile(full_name="Umang"), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([
            {"field_id": "f-nosel", "label": "First Name", "type": "text",
             "options": [], "required": False, "selector": ""},
        ]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["safe_actions"] == []
    review = body["review_actions"]
    assert len(review) == 1
    assert "no selector" in review[0]["reason"]


async def test_file_fields_require_explicit_choice(cleanup, monkeypatch):
    db = FastApplyFakeSession(profile=_profile(), has_resume=True)
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/fast-apply/analyze",
        _analyze_payload([_field("f-cv", "Upload your resume", type="file")]),
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["safe_actions"] == []
    assert "file upload requires an explicit resume choice" in body["review_actions"][0]["reason"]


# ── API surface ───────────────────────────────────────────────────────


async def test_analyze_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/fast-apply/analyze",
            json=_analyze_payload([]),
        )
    assert resp.status_code in (401, 403)


async def test_analyze_rejects_private_url(cleanup, monkeypatch):
    _setup_overrides(FastApplyFakeSession())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/fast-apply/analyze",
            json=_analyze_payload([], page_url="http://127.0.0.1/apply"),
        )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"]


async def test_fast_apply_endpoint_in_openapi():
    spec = app.openapi()
    assert "/api/v1/fast-apply/analyze" in spec["paths"]
