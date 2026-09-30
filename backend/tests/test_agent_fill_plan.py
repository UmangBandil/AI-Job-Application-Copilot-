"""Tests for browser action validation and the deterministic fill planner."""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from app.main import app


# ── Action schema (allow-list) ────────────────────────────────────────

def test_valid_fill_action():
    from app.agent.actions import BrowserAction

    a = BrowserAction(action="FILL", field_id="f1", selector="#name", value="Umang")
    assert a.action.value == "FILL"


def test_rejects_unknown_action_type():
    from app.agent.actions import BrowserAction

    with pytest.raises(ValidationError):
        BrowserAction(action="EXECUTE_JS", field_id="f1")


def test_rejects_extra_fields():
    from app.agent.actions import BrowserAction

    with pytest.raises(ValidationError):
        BrowserAction(action="FILL", field_id="f1", value="x", evil="rm -rf")


def test_control_chars_stripped_from_value():
    from app.agent.actions import BrowserAction

    a = BrowserAction(action="FILL", field_id="f1", value="Um\u0000ang\u200b")
    assert a.value == "Umang"


def test_value_length_cap():
    from app.agent.actions import BrowserAction

    with pytest.raises(ValidationError):
        BrowserAction(action="FILL", field_id="f1", value="x" * 6000)


def test_all_allowed_types_validate():
    from app.agent.actions import ActionType, BrowserAction

    for t in ActionType:
        a = BrowserAction(action=t, field_id="f1")
        assert a.action == t


def test_plan_rejects_over_200_actions():
    from app.agent.actions import ActionPlan, BrowserAction

    with pytest.raises(ValidationError):
        ActionPlan(actions=[BrowserAction(action="WAIT", field_id="f1") for _ in range(201)])


# ── Fixtures/helpers for planner tests ────────────────────────────────

class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeSession:
    def __init__(self, profile=None, question=None):
        self.profile = profile
        self.question = question
        self._first = True

    async def execute(self, stmt):
        if self._first and self.profile is not None:
            self._first = False
            return FakeResult(scalar=self.profile)
        return FakeResult(scalar=self.question)

    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class FakeUser:
    id = uuid.uuid4()
    email = "t@example.com"
    is_active = True


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


def _field(**kw):
    from app.schemas.schemas import PlannedFieldInput

    defaults = dict(field_id="f1", selector="#f1", type="text", action="ai")
    defaults.update(kw)
    return PlannedFieldInput(**defaults)


@pytest.fixture()
def cleanup():
    yield
    app.dependency_overrides.clear()


async def _post_plan(fields):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/v1/agent/fill-plan",
            json={"fields": [f.model_dump() for f in fields]},
        )


def _setup_overrides(db):
    from app.core.database import get_db
    from app.core.deps import get_current_user

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser()


# ── Planner behavior ──────────────────────────────────────────────────

async def test_fill_plan_fills_profile_fields(cleanup):
    _setup_overrides(FakeSession(profile=_profile(full_name="Umang Bandil", email="u@x.com")))
    resp = await _post_plan(
        [
            _field(field_id="fn", selector="#fn", label="First Name", action="profile", profile_key="first_name"),
            _field(field_id="em", selector="#em", label="Email", action="profile", profile_key="email"),
        ]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plan"]) == 2
    fill = body["plan"][0]
    assert fill["action"] == "FILL"
    assert fill["value"] == "Umang"
    assert fill["field_id"] == "fn"


async def test_fill_plan_defers_sensitive_and_ai_fields(cleanup):
    _setup_overrides(FakeSession(profile=_profile(full_name="U")))
    resp = await _post_plan(
        [
            _field(field_id="visa", label="Do you require sponsorship?", action="review", reason="sponsorship"),
            _field(field_id="why", type="textarea", label="Why us?", action="ai"),
        ]
    )
    body = resp.json()
    assert len(body["plan"]) == 0
    assert len(body["needs_review"]) == 1
    assert len(body["needs_ai"]) == 1


async def test_fill_plan_skips_empty_profile_fields(cleanup):
    _setup_overrides(FakeSession(profile=_profile()))
    resp = await _post_plan([_field(field_id="em", label="Email", action="profile", profile_key="email")])
    body = resp.json()
    assert len(body["plan"]) == 0
    assert body["skipped"][0]["reason"].startswith("profile field 'email' is empty")


async def test_fill_plan_select_matches_option_label(cleanup):
    _setup_overrides(FakeSession(profile=_profile(location="Pune")))
    resp = await _post_plan(
        [
            _field(
                field_id="city", type="select", label="Current City",
                action="profile", profile_key="location",
                options=[{"value": "mum", "label": "Mumbai"}, {"value": "pune", "label": "Pune"}],
            )
        ]
    )
    body = resp.json()
    assert len(body["plan"]) == 1
    assert body["plan"][0]["action"] == "SELECT"
    assert body["plan"][0]["option_value"] == "pune"


async def test_fill_plan_memory_exact_match_fills(cleanup):
    now = datetime.now(timezone.utc)
    from app.models import ApplicationQuestion

    rec = ApplicationQuestion(
        id=uuid.uuid4(), user_id=FakeUser.id,
        question="How many years?", normalized_question="experience professional years",
        answer="4", source="user", confidence=1.0, context="", embedding=None,
        created_at=now, updated_at=now,
    )
    _setup_overrides(FakeSession(profile=_profile(full_name="U"), question=rec))
    resp = await _post_plan([_field(field_id="exp", label="How many years?", action="memory")])
    body = resp.json()
    assert len(body["plan"]) == 1
    assert body["plan"][0]["value"] == "4"


async def test_fill_plan_memory_miss_goes_to_needs_ai(cleanup):
    _setup_overrides(FakeSession(profile=_profile(full_name="U"), question=None))
    resp = await _post_plan([_field(field_id="exp", label="How many years?", action="memory")])
    body = resp.json()
    assert len(body["plan"]) == 0
    assert len(body["needs_ai"]) == 1


async def test_fill_plan_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/agent/fill-plan", json={"fields": []})
    assert resp.status_code in (401, 403)


async def test_fill_plan_in_openapi():
    spec = app.openapi()
    assert "/api/v1/agent/fill-plan" in spec["paths"]
