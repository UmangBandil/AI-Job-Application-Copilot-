"""Tests for application question memory (embeddings mocked — no model load)."""

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.main import app

FAKE_VEC = [0.1] * 384


# ── Normalization ─────────────────────────────────────────────────────

def test_normalize_equivalent_questions_match():
    from app.ai.retrieval.question_memory import normalize_question

    a = normalize_question("Do you have experience with Java?")
    b = normalize_question("Have you worked with Java before?")
    c = normalize_question("Do you know Java?")
    assert a == b == c == "experience java"


def test_normalize_preserves_work_authorization():
    from app.ai.retrieval.question_memory import normalize_question

    # "work" must NOT fold into "experience" (sensitive-question safety)
    assert normalize_question("Do you have work authorization?") == "authorization work"


def test_normalize_dedupes_and_sorts():
    from app.ai.retrieval.question_memory import normalize_question

    assert normalize_question("Java? java! JAVA") == "java"
    assert normalize_question("willing to relocate") == "relocate willing"


def test_normalize_strips_punctuation_and_stopwords():
    from app.ai.retrieval.question_memory import normalize_question

    result = normalize_question("What is your expected salary, and why?")
    assert result == "expected salary"


# ── save_answer ───────────────────────────────────────────────────────

class FakeResult:
    def __init__(self, scalar=None, rows=None, items=None):
        self._scalar = scalar
        self._rows = rows if rows is not None else []
        self._items = items if items is not None else []

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows

    def scalars(self):
        outer = self

        class _Scalars:
            def all(self_inner):
                return outer._items

        return _Scalars()


class FakeSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.added = []

    async def execute(self, stmt):
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class FakeUser:
    id = uuid.uuid4()
    email = "test@example.com"
    is_active = True


async def test_save_answer_stores_record_with_embedding(monkeypatch):
    from app.ai.retrieval import question_memory as qm

    monkeypatch.setattr(qm, "embed_query", lambda q: FAKE_VEC)
    db = FakeSession()
    record = await qm.save_answer(db, FakeUser.id, "Do you know Java?", "Yes — 3 years", source="user")
    assert record.answer == "Yes — 3 years"
    assert record.source == "user"
    assert record.embedding == FAKE_VEC
    assert record.normalized_question == "experience java"
    assert db.added == [record]


# ── find_similar_questions ────────────────────────────────────────────

def _record(**kwargs):
    from app.models import ApplicationQuestion

    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        user_id=FakeUser.id,
        question="Q",
        normalized_question="q",
        answer="A",
        source="user",
        confidence=1.0,
        context="",
        embedding=FAKE_VEC,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return ApplicationQuestion(**defaults)


async def test_exact_normalized_match_short_circuits(monkeypatch):
    from app.ai.retrieval import question_memory as qm

    def _boom(_q):
        raise AssertionError("embedding must not be called on the exact path")

    monkeypatch.setattr(qm, "embed_query", _boom)
    exact = _record(question="Do you have experience with Java?", normalized_question="experience java")
    db = FakeSession(results=[FakeResult(scalar=exact)])

    matches = await qm.find_similar_questions(db, FakeUser(), "Have you worked with Java before?")
    assert len(matches) == 1
    assert matches[0]["similarity"] == 1.0
    assert matches[0]["answer"] == "A"


async def test_vector_search_ranks_user_above_llm(monkeypatch):
    from app.ai.retrieval import question_memory as qm

    monkeypatch.setattr(qm, "embed_query", lambda q: FAKE_VEC)

    user_rec = _record(answer="user answer", source="user")
    llm_rec = _record(answer="llm answer", source="llm")
    # llm record is *more* similar but has lower authority — user must win.
    db = FakeSession(results=[FakeResult(scalar=None), FakeResult(rows=[(user_rec, 0.10), (llm_rec, 0.02)])])

    matches = await qm.find_similar_questions(db, FakeUser(), "Do you know Java?", min_similarity=0.8)
    assert [m["answer"] for m in matches] == ["user answer", "llm answer"]
    assert matches[0]["similarity"] == pytest.approx(0.9)


async def test_vector_search_filters_below_threshold(monkeypatch):
    from app.ai.retrieval import question_memory as qm

    monkeypatch.setattr(qm, "embed_query", lambda q: FAKE_VEC)
    far = _record(answer="far")
    db = FakeSession(results=[FakeResult(scalar=None), FakeResult(rows=[(far, 0.5)])])  # sim 0.5 < 0.8

    matches = await qm.find_similar_questions(db, FakeUser(), "unrelated question?")
    assert matches == []


# ── API ───────────────────────────────────────────────────────────────

class FakeUser2(FakeUser):
    pass


def _client(db_session: FakeSession):
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser2()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture()
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


async def test_create_answer_endpoint(cleanup_overrides, monkeypatch):
    from app.ai.retrieval import question_memory as qm

    monkeypatch.setattr(qm, "embed_query", lambda q: FAKE_VEC)
    async with _client(FakeSession()) as client:
        resp = await client.post(
            "/api/v1/memory/answers",
            json={"question": "Are you willing to relocate?", "answer": "Yes", "source": "user"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["answer"] == "Yes"
    assert body["normalized_question"] == "relocate willing"


async def test_search_endpoint_exact_path(cleanup_overrides):
    exact = _record(question="Why do you want this job?", normalized_question="job want")
    async with _client(FakeSession(results=[FakeResult(scalar=exact)])) as client:
        resp = await client.get("/api/v1/memory/search", params={"q": "Why do you want this role?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matches"][0]["answer"] == "A"


async def test_list_answers_endpoint(cleanup_overrides):
    rec = _record()
    async with _client(FakeSession(results=[FakeResult(items=[rec])])) as client:
        resp = await client.get("/api/v1/memory/answers")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_update_answer_promotes_edit_to_user_source(cleanup_overrides):
    rec = _record(source="llm", confidence=0.7)
    async with _client(FakeSession(results=[FakeResult(scalar=rec)])) as client:
        resp = await client.patch(f"/api/v1/memory/answers/{rec.id}", json={"answer": "edited answer"})
    assert resp.status_code == 200
    assert rec.answer == "edited answer"
    assert rec.source == "user"
    assert rec.confidence == 1.0


async def test_update_answer_404_for_other_users(cleanup_overrides):
    async with _client(FakeSession(results=[FakeResult(scalar=None)])) as client:
        resp = await client.patch(f"/api/v1/memory/answers/{uuid.uuid4()}", json={"answer": "x"})
    assert resp.status_code == 404


async def test_memory_endpoints_require_auth():
    from app.core.database import get_db
    from app.core.deps import get_current_user

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/memory/answers")
    app.dependency_overrides.clear()
    assert resp.status_code in (401, 403)


async def test_memory_routes_in_openapi():
    spec = app.openapi()
    assert "/api/v1/memory/search" in spec["paths"]
    assert "/api/v1/memory/answers" in spec["paths"]


# ── Migrations ────────────────────────────────────────────────────────

def test_migration_chain_head_is_application_questions():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["0004_create_application_questions"]


def test_memory_model_registered_on_metadata():
    import app.models.all  # noqa: F401
    from app.core.database import Base

    assert "application_questions" in Base.metadata.tables
