"""Tests for the M5 answer engine: field policy, agent pipeline, endpoints.

No live LLM, no database: providers are fakes (monkeypatched at the
answer_agent module boundary), sessions are routing fakes, and embed_query
is stubbed so the sentence-transformers model never loads.
"""

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


class FakeSession:
    """Routes statements by table name, like the real query mix."""

    def __init__(self, profile=None, question=None, chunk_rows=None):
        self.profile = profile
        self.question = question
        self.chunk_rows = chunk_rows or []
        self.added = []

    async def execute(self, stmt):
        sql = str(stmt)
        if "profiles" in sql:
            return FakeResult(scalar=self.profile)
        if "resume_chunks" in sql:
            return FakeResult(rows=self.chunk_rows)
        if "application_questions" in sql:
            if "<=>" in sql:  # pgvector cosine semantic search
                return FakeResult(rows=[])
            return FakeResult(scalar=self.question)
        return FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

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
        raise AssertionError("LLM must not be called for this question")


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


def _memory_record(question="How many years of experience do you have?", answer="4"):
    from app.models import ApplicationQuestion

    now = datetime.now(timezone.utc)
    return ApplicationQuestion(
        id=uuid.uuid4(), user_id=FakeUser.id,
        question=question,
        normalized_question="experience many years",
        answer=answer, source="user", confidence=1.0, context="", embedding=None,
        created_at=now, updated_at=now,
    )


@pytest.fixture(autouse=True)
def fast_env(monkeypatch):
    """Stub embeddings so no model loads, and always provide a provider."""
    import app.ai.agents.answer_agent as aa
    import app.ai.retrieval.question_memory as qm

    fake_vec = [0.1] * 384
    monkeypatch.setattr(aa, "embed_query", lambda q: fake_vec)
    monkeypatch.setattr(qm, "embed_query", lambda q: fake_vec)


async def _generate(db=None, provider=None, **kw):
    import app.ai.agents.answer_agent as aa

    if provider is not None:
        # get_llm_provider is called lazily inside generate_answer.
        import app.ai.providers.base as base

        original = base.get_llm_provider

        def fake_factory():
            return provider

        # answer_agent imported the symbol directly; patch both views.
        aa.get_llm_provider = fake_factory  # type: ignore[method-assign]
        try:
            return await aa.generate_answer(db or FakeSession(), FakeUser(), **kw)
        finally:
            aa.get_llm_provider = original  # type: ignore[method-assign]
    return await aa.generate_answer(db or FakeSession(), FakeUser(), **kw)


# ── Field policy engine ───────────────────────────────────────────────

def test_policy_sensitive_sponsorship():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    policy, reason, _confidence = classify_question("Do you require visa sponsorship?")
    assert policy is AnswerPolicy.USER_CONFIRMATION_REQUIRED
    assert "sponsorship" in reason


@pytest.mark.parametrize(
    "q",
    [
        "Are you legally authorized to work in the US?",
        "What is your expected salary?",
        "What is your gender?",
        "Are you willing to relocate?",
        "Are you able to travel 50%?",
        "What is your notice period?",
        "Have you ever been convicted of a crime?",
    ],
)
def test_policy_all_sensitive_topics(q):
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    policy, _, _confidence = classify_question(q)
    assert policy is AnswerPolicy.USER_CONFIRMATION_REQUIRED


def test_policy_years_experience_is_profile_or_memory():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    policy, reason, _confidence = classify_question("How many years of experience do you have?")
    assert policy is AnswerPolicy.PROFILE_OR_MEMORY
    assert "experience length" in reason


def test_policy_email_is_profile_only():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    policy, reason, _confidence = classify_question("What is your email address?")
    assert policy is AnswerPolicy.PROFILE_ONLY
    assert "email" in reason


def test_policy_open_textarea_is_llm_generated():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    policy, _, _confidence = classify_question("Why do you want to work here?", field_type="textarea")
    assert policy is AnswerPolicy.LLM_GENERATED


def test_policy_unknown_choice_is_profile_or_memory():
    from app.ai.agents.field_policy import AnswerPolicy, classify_question

    policy, _, _confidence = classify_question("Preferred work style?", field_type="select")
    assert policy is AnswerPolicy.PROFILE_OR_MEMORY


def test_client_policy_mismatch_detection():
    from app.ai.agents.field_policy import AnswerPolicy, client_policy_matches

    # Server says sensitive; a client claiming "ai" is a mismatch.
    assert client_policy_matches(AnswerPolicy.USER_CONFIRMATION_REQUIRED, "review") is True
    assert client_policy_matches(AnswerPolicy.LLM_GENERATED, "ai") is True
    assert client_policy_matches(AnswerPolicy.USER_CONFIRMATION_REQUIRED, "ai") is False
    assert client_policy_matches(AnswerPolicy.PROFILE_ONLY, "memory") is False


# ── Agent pipeline ────────────────────────────────────────────────────

async def test_sensitive_question_never_reaches_llm():
    resp = await _generate(
        db=FakeSession(profile=_profile(email="u@x.com")),
        provider=NeverCalledProvider(),
        question="Do you require sponsorship?",
    )
    assert resp.requires_review is True
    assert resp.answer is None
    assert resp.source == "none"
    assert "Sensitive topic" in resp.notes
    assert resp.fill_action is None


async def test_sensitive_with_client_mismatch_records_anomaly():
    resp = await _generate(
        db=FakeSession(),
        provider=NeverCalledProvider(),
        question="What is your expected salary?",
        client_policy="ai",  # a naive/tampered client tried the LLM bucket
    )
    assert resp.requires_review is True
    assert resp.anomalies and "client classified as 'ai'" in resp.anomalies[0]


async def test_profile_question_answered_deterministically():
    resp = await _generate(
        db=FakeSession(profile=_profile(email="umang@example.com")),
        provider=NeverCalledProvider(),
        question="What is your email address?",
        field_id="f-email",
        selector="#email",
    )
    assert resp.answer == "umang@example.com"
    assert resp.source == "profile"
    assert resp.requires_review is False
    assert resp.confidence == 1.0
    assert resp.fill_action == {
        "action": "FILL", "field_id": "f-email", "selector": "#email",
        "value": "umang@example.com", "option_value": None, "checked": None,
        "pixels": None, "milliseconds": None,
    }


async def test_profile_select_matches_option_value():
    resp = await _generate(
        db=FakeSession(profile=_profile(location="Pune")),
        provider=NeverCalledProvider(),
        question="What city are you located in?",
        field_type="select",
        field_options=[{"value": "mum", "label": "Mumbai"}, {"value": "pune", "label": "Pune"}],
        field_id="f-city",
    )
    assert resp.source == "profile"
    assert resp.fill_action["action"] == "SELECT"
    assert resp.fill_action["option_value"] == "pune"


async def test_profile_missing_value_falls_back_to_memory():
    resp = await _generate(
        db=FakeSession(profile=_profile(), question=_memory_record(answer="4")),
        provider=NeverCalledProvider(),
        question="How many years of experience do you have?",
        field_id="f-exp",
    )
    assert resp.source == "memory"
    assert resp.answer == "4"
    assert resp.requires_review is False


async def test_profile_and_memory_miss_requires_review_without_llm():
    resp = await _generate(
        db=FakeSession(profile=_profile()),
        provider=NeverCalledProvider(),
        question="How many years of experience do you have?",
    )
    assert resp.answer is None
    assert resp.requires_review is True
    assert "answer this yourself" in resp.notes


async def test_llm_happy_path_with_fill_action():
    resp = await _generate(
        db=FakeSession(profile=_profile(full_name="Umang", skills=["python"])),
        provider=FakeProvider([{"answer": "I enjoy building developer tools.", "confidence": 0.92, "notes": "used skills"}]),
        question="Why do you want to work here?",
        field_type="textarea",
        field_id="f-why",
    )
    assert resp.source == "llm"
    assert resp.answer == "I enjoy building developer tools."
    assert resp.requires_review is False
    assert resp.fill_action["action"] == "FILL"
    assert resp.fill_action["value"] == "I enjoy building developer tools."


async def test_llm_low_confidence_gates_to_review():
    resp = await _generate(
        db=FakeSession(profile=_profile()),
        provider=FakeProvider([{"answer": "A guess.", "confidence": 0.3, "notes": ""}]),
        question="Describe your ideal role.",
    )
    assert resp.requires_review is True
    assert resp.fill_action is None
    assert resp.answer == "A guess."  # shown to the human, not filled


async def test_llm_insufficient_context_never_answers():
    resp = await _generate(
        db=FakeSession(profile=_profile()),
        provider=FakeProvider([{"answer": "insufficient_context", "confidence": 0.8, "notes": "no data"}]),
        question="Describe your leadership philosophy.",
    )
    assert resp.answer is None
    assert resp.requires_review is True
    assert resp.llm_raw == "insufficient_context"


async def test_llm_invalid_output_retries_then_recovers():
    provider = FakeProvider([
        {"confidence": 0.9},  # missing answer -> invalid
        {"answer": "Recovered answer.", "confidence": 0.9, "notes": ""},
    ])
    resp = await _generate(
        db=FakeSession(profile=_profile()),
        provider=provider,
        question="Tell us about a project you are proud of.",
    )
    assert provider.calls == 2
    assert resp.answer == "Recovered answer."


async def test_llm_offline_returns_review_fallback():
    from app.ai.providers.base import LLMError

    provider = FakeProvider([LLMError("Cannot reach Ollama — is it running?")])
    resp = await _generate(
        db=FakeSession(profile=_profile()),
        provider=provider,
        question="What excites you about this role?",
    )
    assert resp.requires_review is True
    assert resp.answer is None
    assert "Cannot reach Ollama" in resp.notes


async def test_llm_select_answer_must_match_allowed_options():
    # First reply is not an allowed option; retry is (by label).
    provider = FakeProvider([
        {"answer": "Somewhere nice", "confidence": 0.99, "notes": ""},
        {"answer": "Hybrid", "confidence": 0.95, "notes": ""},
    ])
    resp = await _generate(
        db=FakeSession(profile=_profile()),
        provider=provider,
        question="What is your preferred work setup?",
        field_type="select",
        field_options=[{"value": "1", "label": "Remote"}, {"value": "2", "label": "Hybrid"}],
        field_id="f-setup",
    )
    assert provider.calls == 2
    assert resp.fill_action["action"] == "SELECT"
    assert resp.fill_action["option_value"] == "2"


async def test_resume_chunks_grounded_in_prompt():
    from app.models import Resume, ResumeChunk

    now = datetime.now(timezone.utc)
    resume = Resume(id=uuid.uuid4(), user_id=FakeUser.id, title="Main resume", file_name="r.pdf", raw_text="x", is_active=True, created_at=now, updated_at=now)
    chunk = ResumeChunk(id=uuid.uuid4(), resume_id=resume.id, chunk_text="Led a team of 5 engineers", chunk_type="experience", metadata_={}, embedding=None)

    captured = {}

    class CaptureProvider(FakeProvider):
        async def generate_json(self, prompt, system="", max_tokens=2000):
            captured["prompt"] = prompt
            return {"answer": "I led a team of 5 engineers.", "confidence": 0.9, "notes": ""}

    resp = await _generate(
        db=FakeSession(profile=_profile(), chunk_rows=[(chunk, resume, 0.1)]),
        provider=CaptureProvider(),
        question="Describe your leadership experience.",
    )
    assert "Led a team of 5 engineers" in captured["prompt"]
    assert "RESUME EXCERPTS" in captured["prompt"]
    assert resp.source == "llm"


# ── API endpoints ─────────────────────────────────────────────────────

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


async def test_answer_endpoint_happy_path(cleanup, monkeypatch):
    _setup_overrides(FakeSession(profile=_profile(full_name="Umang Bandil")))
    provider = FakeProvider([{"answer": "I want to build tools.", "confidence": 0.9, "notes": ""}])
    resp = await _post(
        "/api/v1/agent/answer",
        {"question": "Why do you want to work here?", "field_type": "textarea"},
        monkeypatch,
        provider,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "llm"
    assert body["requires_review"] is False
    assert body["fill_action"]["value"] == "I want to build tools."


async def test_answer_endpoint_sensitive_needs_review(cleanup, monkeypatch):
    _setup_overrides(FakeSession(profile=_profile()))
    resp = await _post(
        "/api/v1/agent/answer",
        {"question": "Do you require sponsorship?"},
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy"] == "user_confirmation_required"
    assert body["requires_review"] is True
    assert body["answer"] is None


async def test_answer_endpoint_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/agent/answer", json={"question": "Why us?"})
    assert resp.status_code in (401, 403)


async def test_save_answer_endpoint_stores_in_memory(cleanup, monkeypatch):
    db = FakeSession(profile=_profile())
    _setup_overrides(db)
    resp = await _post(
        "/api/v1/agent/answers/save",
        {"question": "How many years of experience do you have?", "answer": "4", "source": "user"},
        monkeypatch,
        NeverCalledProvider(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy"] == "saved"
    assert body["answer"] == "4"
    assert len(db.added) == 1  # an ApplicationQuestion was staged


async def test_save_answer_rejects_bad_source(cleanup):
    _setup_overrides(FakeSession())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/agent/answers/save",
            json={"question": "Q", "answer": "A", "source": "admin"},
        )
    assert resp.status_code == 422


async def test_answer_endpoints_in_openapi():
    spec = app.openapi()
    assert "/api/v1/agent/answer" in spec["paths"]
    assert "/api/v1/agent/answers/save" in spec["paths"]
