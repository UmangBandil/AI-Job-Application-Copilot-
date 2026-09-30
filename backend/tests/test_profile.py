"""Tests for the candidate profile API and retriever (fake DB session)."""

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.main import app


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class FakeSession:
    """Minimal AsyncSession stand-in for profile queries."""

    def __init__(self, profile=None):
        self.profile = profile
        self.added = []
        self.flush_count = 0

    async def execute(self, stmt):
        return FakeResult([self.profile] if self.profile is not None else [])

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at

    async def flush(self):
        self.flush_count += 1

    async def refresh(self, obj):
        pass


class FakeUser:
    id = uuid.uuid4()
    email = "test@example.com"
    is_active = True

# Real client factory: overrides auth + DB dependencies on the live app.
def _client(db_session: FakeSession):
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture()
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def _make_profile(**kwargs):
    from app.models import Profile

    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        user_id=FakeUser.id,
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
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return Profile(**defaults)


# ── API ───────────────────────────────────────────────────────────────

async def test_get_profile_creates_empty_on_first_access(cleanup_overrides):
    db = FakeSession(profile=None)
    async with _client(db) as client:
        resp = await client.get("/api/v1/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == ""
    assert body["skills"] == []
    assert len(db.added) == 1  # profile was created
    assert body["id"] == str(db.added[0].id)


async def test_get_profile_returns_existing(cleanup_overrides):
    db = FakeSession(profile=_make_profile(full_name="Umang Bandil", skills=["python", "react"]))
    async with _client(db) as client:
        resp = await client.get("/api/v1/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Umang Bandil"
    assert body["skills"] == ["python", "react"]
    assert db.added == []


async def test_patch_profile_updates_only_provided_fields(cleanup_overrides):
    db = FakeSession(profile=_make_profile(full_name="Old Name"))
    async with _client(db) as client:
        resp = await client.patch(
            "/api/v1/profile",
            json={"full_name": "Umang Bandil", "location": "Pune, Maharashtra"},
        )
    assert resp.status_code == 200
    profile = db.profile
    assert profile.full_name == "Umang Bandil"
    assert profile.location == "Pune, Maharashtra"
    assert profile.phone == ""  # untouched
    assert profile.notice_period == ""  # untouched


async def test_patch_profile_creates_if_missing(cleanup_overrides):
    db = FakeSession(profile=None)
    async with _client(db) as client:
        resp = await client.patch("/api/v1/profile", json={"github_url": "https://github.com/umang"})
    assert resp.status_code == 200
    assert db.added[0].github_url == "https://github.com/umang"


async def test_profile_requires_auth():
    from app.core.database import get_db
    from app.core.deps import get_current_user

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/profile")
    app.dependency_overrides.clear()
    assert resp.status_code in (401, 403)


async def test_profile_routes_in_openapi():
    spec = app.openapi()
    assert "/api/v1/profile" in spec["paths"]
    assert set(spec["paths"]["/api/v1/profile"]) == {"get", "patch"}


# ── Retriever ─────────────────────────────────────────────────────────

async def test_retriever_get_or_create_returns_existing():
    from app.ai.retrieval.profile_retriever import get_or_create_profile

    existing = _make_profile(full_name="Existing")
    db = FakeSession(profile=existing)
    result = await get_or_create_profile(db, FakeUser())
    assert result is existing
    assert db.added == []


async def test_retriever_get_or_create_creates_when_missing():
    from app.ai.retrieval.profile_retriever import get_or_create_profile

    db = FakeSession(profile=None)
    result = await get_or_create_profile(db, FakeUser())
    assert len(db.added) == 1
    assert result is db.added[0]


def test_build_profile_context_omits_empty_fields():
    from app.ai.retrieval.profile_retriever import build_profile_context

    profile = _make_profile(full_name="Umang", email="", skills=["python"], salary_expectation="")
    context = build_profile_context(profile)
    assert context["full_name"] == "Umang"
    assert "email" not in context
    assert context["skills"] == ["python"]
    assert "salary_expectation" not in context
    assert "work_authorization" not in context


def test_build_profile_context_includes_structured_data():
    from app.ai.retrieval.profile_retriever import build_profile_context

    profile = _make_profile(
        education=[{"degree": "B.Tech", "institution": "X University"}],
        work_authorization={"status": "Indian citizen", "requires_sponsorship": False},
        willing_to_relocate=True,
    )
    context = build_profile_context(profile)
    assert context["education"] == [{"degree": "B.Tech", "institution": "X University"}]
    assert context["work_authorization"] == {"status": "Indian citizen", "requires_sponsorship": False}
    assert context["willing_to_relocate"] is True


# ── Migrations ────────────────────────────────────────────────────────

def test_migration_chain_head_is_profiles():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["0003_create_profiles"]


def test_profile_model_registered_on_metadata():
    import app.models.all  # noqa: F401
    from app.core.database import Base

    assert "profiles" in Base.metadata.tables
