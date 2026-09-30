"""Unit tests for the LLM provider abstraction.

No real LLM or Ollama instance is required — network interactions are
simulated with httpx.MockTransport and provider selection is tested via
environment variables.
"""

import socket

import httpx
import pytest

from app.ai.providers.base import (
    LLMError,
    OllamaProvider,
    OpenAIProvider,
    AnthropicProvider,
    extract_json_object,
    get_llm_provider,
)
from app.core.config import get_settings


# ── JSON extraction ───────────────────────────────────────────────────

def test_extract_json_plain():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = 'Here is your JSON:\n```json\n{"a": 1, "b": [2, 3]}\n```\nDone.'
    assert extract_json_object(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_with_prose():
    text = 'Sure! {"answer": "Yes", "confidence": 0.9} hope that helps'
    assert extract_json_object(text) == {"answer": "Yes", "confidence": 0.9}


def test_extract_json_no_object_raises():
    with pytest.raises(LLMError):
        extract_json_object("no json here at all")


def test_extract_json_invalid_raises():
    with pytest.raises(LLMError):
        extract_json_object('{"a": 1,,}')


def test_extract_json_non_object_raises():
    with pytest.raises(LLMError):
        extract_json_object("[1, 2, 3]")


# ── Ollama provider over MockTransport ────────────────────────────────

def make_provider(model="test-model", base_url="http://test:11434"):
    return OllamaProvider(base_url=base_url, model=model, timeout_seconds=5)


def patch_transport(monkeypatch, provider, handler):
    def fake_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)

    monkeypatch.setattr(provider, "_client", fake_client)


async def test_ollama_generate_success(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = request.read()
        return httpx.Response(200, json={"response": "hello from local model"})

    provider = make_provider()
    patch_transport(monkeypatch, provider, handler)

    result = await provider.generate("What is 2+2?", system="Be brief.")
    assert result == "hello from local model"
    assert seen["url"].endswith("/api/generate")

    import json

    payload = json.loads(seen["payload"])
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert "Be brief." in payload["prompt"]
    assert "What is 2+2?" in payload["prompt"]


async def test_ollama_generate_json_sends_format_json(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = request.read()
        return httpx.Response(200, json={"response": '{"x": 1, "y": "two"}'})

    provider = make_provider()
    patch_transport(monkeypatch, provider, handler)

    result = await provider.generate_json("Return JSON")
    assert result == {"x": 1, "y": "two"}

    import json

    assert json.loads(seen["payload"])["format"] == "json"


async def test_ollama_unreachable_raises_friendly_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = make_provider()
    patch_transport(monkeypatch, provider, handler)

    with pytest.raises(LLMError, match="Cannot reach Ollama"):
        await provider.generate("hi")


async def test_ollama_model_missing_error_mentions_pull(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not found")

    provider = make_provider(model="nope:1b")
    patch_transport(monkeypatch, provider, handler)

    with pytest.raises(LLMError, match="ollama pull"):
        await provider.generate("hi")


async def test_ollama_health_check_reports_models(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/api/tags")
        return httpx.Response(
            200,
            json={"models": [{"name": "test-model:latest"}, {"name": "llama3:8b"}]},
        )

    provider = make_provider()
    patch_transport(monkeypatch, provider, handler)

    status = await provider.health_check()
    assert status["connected"] is True
    assert status["model_available"] is True
    assert "llama3:8b" in status["available_models"]


async def test_ollama_health_check_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = make_provider()
    patch_transport(monkeypatch, provider, handler)

    with pytest.raises(LLMError):
        await provider.health_check()


# ── Cloud providers ───────────────────────────────────────────────────

async def test_openai_generate_json_extracts_object(monkeypatch):
    provider = OpenAIProvider(api_key="k", model="gpt-4o", timeout_seconds=5)

    async def fake_generate(prompt, system="", max_tokens=2000):
        return '```json\n{"done": true}\n```'

    monkeypatch.setattr(provider, "generate", fake_generate)
    assert await provider.generate_json("p") == {"done": True}


async def test_anthropic_generate_json_extracts_object(monkeypatch):
    provider = AnthropicProvider(api_key="k", model="claude-x", timeout_seconds=5)

    async def fake_generate(prompt, system="", max_tokens=2000):
        return '{"done": true} trailing prose'

    monkeypatch.setattr(provider, "generate", fake_generate)
    assert await provider.generate_json("p") == {"done": True}


# ── Factory / settings-driven selection ───────────────────────────────

@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    """Isolate tests from developer .env files and each other."""
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_llm_provider.cache_clear()
    get_settings.cache_clear()
    yield
    get_llm_provider.cache_clear()
    get_settings.cache_clear()


def test_factory_no_configuration_raises():
    with pytest.raises(LLMError, match="No LLM provider configured"):
        get_llm_provider()


def test_factory_selects_ollama_with_env_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11500")
    monkeypatch.setenv("OLLAMA_MODEL", "my-custom-model")

    provider = get_llm_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "my-custom-model"
    assert provider.base_url == "http://127.0.0.1:11500"


def test_factory_openai_requires_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        get_llm_provider()


def test_factory_openai_with_custom_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    provider = get_llm_provider()
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-4o-mini"


def test_factory_anthropic_requires_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        get_llm_provider()


def test_factory_auto_detect_prefers_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    provider = get_llm_provider()
    assert isinstance(provider, AnthropicProvider)


def test_factory_auto_detect_falls_back_to_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    provider = get_llm_provider()
    assert isinstance(provider, OpenAIProvider)


# ── SECRET_KEY fail-fast (audit item) ────────────────────────────────

def test_secret_key_fails_fast_in_production(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        get_settings()
    get_settings.cache_clear()
