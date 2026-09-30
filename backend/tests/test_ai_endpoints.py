"""API tests for /api/v1/ai endpoints.

Runs the real FastAPI app via httpx.ASGITransport with dependency
overrides (auth, DB) and a fake LLM provider — no network, no database.
"""

import httpx
import pytest

from app.main import app


class FakeProvider:
    name = "fake"

    async def generate(self, prompt, system="", max_tokens=2000):
        return "FAKE-CONTENT"

    async def generate_json(self, prompt, system="", max_tokens=2000):
        return {"ok": True, "answer": "stub"}

    async def health_check(self):
        return {"provider": "fake", "connected": True, "model": "fake-model"}


class UnreachableProvider(FakeProvider):
    name = "fake-offline"

    async def health_check(self):
        from app.ai.providers.base import LLMError

        raise LLMError("Cannot reach Ollama at http://localhost:11434 — is it running?")

    async def generate(self, prompt, system="", max_tokens=2000):
        from app.ai.providers.base import LLMError

        raise LLMError("Cannot reach Ollama at http://localhost:11434 — is it running?")

    async def generate_json(self, prompt, system="", max_tokens=2000):
        from app.ai.providers.base import LLMError

        raise LLMError("Cannot reach Ollama at http://localhost:11434 — is it running?")


class FakeUser:
    id = "00000000-0000-0000-0000-000000000001"
    email = "test@example.com"
    is_active = True


async def fake_db():
    yield object()  # never used by /ai endpoints


@pytest.fixture()
def client(monkeypatch):
    import app.api.ai as ai_module

    monkeypatch.setattr(ai_module, "get_llm_provider", lambda: FakeProvider())
    app.dependency_overrides[ai_module.get_db] = fake_db
    app.dependency_overrides[ai_module.get_current_user] = lambda: FakeUser()
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture()
def offline_client(monkeypatch):
    import app.api.ai as ai_module

    monkeypatch.setattr(ai_module, "get_llm_provider", lambda: UnreachableProvider())
    app.dependency_overrides[ai_module.get_db] = fake_db
    app.dependency_overrides[ai_module.get_current_user] = lambda: FakeUser()
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


# ── Health ────────────────────────────────────────────────────────────

async def test_ai_health_connected(client):
    resp = await client.get("/api/v1/ai/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["connected"] is True
    assert body["provider"] == "fake"
    assert body["model"] == "fake-model"


async def test_ai_health_reports_offline_as_200(offline_client):
    resp = await offline_client.get("/api/v1/ai/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["connected"] is False
    assert "Cannot reach Ollama" in body["detail"]["error"]


async def test_ai_endpoints_require_auth(monkeypatch):
    import app.api.ai as ai_module

    monkeypatch.setattr(ai_module, "get_llm_provider", lambda: FakeProvider())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/ai/health")
    assert resp.status_code in (401, 403)


# ── Chat ──────────────────────────────────────────────────────────────

async def test_ai_chat_returns_content(client):
    resp = await client.post("/api/v1/ai/chat", json={"prompt": "hi", "system": "be brief"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "FAKE-CONTENT"
    assert body["provider"] == "fake"


async def test_ai_chat_offline_is_503_with_message(offline_client):
    resp = await offline_client.post("/api/v1/ai/chat", json={"prompt": "hi"})
    assert resp.status_code == 503
    assert "Cannot reach Ollama" in resp.json()["detail"]


async def test_ai_chat_validates_payload(client):
    resp = await client.post("/api/v1/ai/chat", json={})
    assert resp.status_code == 422


# ── generate-json ─────────────────────────────────────────────────────

async def test_generate_json_returns_data(client):
    resp = await client.post(
        "/api/v1/ai/generate-json",
        json={"prompt": "p", "required_keys": ["answer"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["ok"] is True
    assert body["provider"] == "fake"


async def test_generate_json_enforces_required_keys(client):
    resp = await client.post(
        "/api/v1/ai/generate-json",
        json={"prompt": "p", "required_keys": ["answer", "confidence"]},
    )
    assert resp.status_code == 502
    assert "confidence" in resp.json()["detail"]


async def test_generate_json_offline_is_503(offline_client):
    resp = await offline_client.post("/api/v1/ai/generate-json", json={"prompt": "p"})
    assert resp.status_code == 503


# ── Routing / registration ────────────────────────────────────────────

async def test_ai_routes_registered_in_openapi():
    spec = app.openapi()
    assert "/api/v1/ai/health" in spec["paths"]
    assert "/api/v1/ai/chat" in spec["paths"]
    assert "/api/v1/ai/generate-json" in spec["paths"]


# ── generation_service seam ───────────────────────────────────────────

async def test_generation_service_uses_provider_factory(monkeypatch):
    import app.services.generation_service as gs

    called = {}

    class RecordingProvider(FakeProvider):
        async def generate(self, prompt, system="", max_tokens=2000):
            called["prompt"] = prompt
            called["system"] = system
            return "PROVIDER-OUTPUT"

    monkeypatch.setattr(gs, "get_llm_provider", lambda: RecordingProvider())
    result = await gs._call_llm("the prompt", system="the system", max_tokens=100)
    assert result == "PROVIDER-OUTPUT"
    assert called["prompt"] == "the prompt"
    assert called["system"] == "the system"
