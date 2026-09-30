"""LLM provider abstraction.

All providers implement the same async interface:
generate()      -> raw text completion
generate_json() -> dict parsed from a JSON object the model returns
health_check()  -> reachability probe (raises LLMError when unavailable)

Selection is driven by the LLM_PROVIDER setting; see get_llm_provider().
"""

import json
import re
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx

from app.core.config import get_settings


class LLMError(RuntimeError):
    """Raised when the configured LLM provider is unreachable or fails."""


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from LLM output.

    Tolerates markdown fences and surrounding prose, which small local
    models frequently emit even when asked for JSON only.
    """
    text = text.strip()

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError(f"LLM returned no JSON object: {text[:200]!r}")

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned invalid JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise LLMError("LLM returned JSON that is not an object")
    return parsed


class LLMProvider(ABC):
    """Common interface for all LLM backends (local and cloud)."""

    name: str = "base"

    @abstractmethod
    async def generate(self, prompt: str, system: str = "", max_tokens: int = 2000) -> str:
        """Return a raw text completion."""

    @abstractmethod
    async def generate_json(self, prompt: str, system: str = "", max_tokens: int = 2000) -> dict:
        """Return a JSON object parsed from the model's output."""

    @abstractmethod
    async def health_check(self) -> dict:
        """Return provider status info; raise LLMError if unavailable."""

    def _build_user_content(self, prompt: str, system: str) -> str:
        if system:
            return f"{system}\n\n{prompt}"
        return prompt


class OllamaProvider(LLMProvider):
    """Local LLM via the Ollama HTTP API (default: http://localhost:11434).

    No API key required. Model name comes from OLLAMA_MODEL (never hard-coded).
    """

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_seconds)

    async def _request(self, payload: dict) -> dict:
        try:
            async with self._client() as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            raise LLMError(
                f"Ollama returned HTTP {e.response.status_code} for model '{self.model}' "
                f"(is the model pulled? try: ollama pull {self.model})"
            ) from e
        except (httpx.HTTPError, OSError) as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.base_url} — is it running? "
                f"Start it with: ollama serve"
            ) from e

    async def generate(self, prompt: str, system: str = "", max_tokens: int = 2000) -> str:
        payload = {
            "model": self.model,
            "prompt": self._build_user_content(prompt, system),
            "stream": False,
        }
        data = await self._request(payload)
        return data.get("response", "")

    async def generate_json(self, prompt: str, system: str = "", max_tokens: int = 2000) -> dict:
        payload = {
            "model": self.model,
            "prompt": self._build_user_content(prompt, system),
            "stream": False,
            "format": "json",
        }
        data = await self._request(payload)
        return extract_json_object(data.get("response", ""))

    async def health_check(self) -> dict:
        try:
            async with self._client() as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                tags = resp.json()
        except (httpx.HTTPError, OSError) as e:
            raise LLMError(f"Cannot reach Ollama at {self.base_url}: {e}") from e

        models = [m.get("name", "") for m in tags.get("models", [])]
        model_available = any(m == self.model or m.split(":")[0] == self.model.split(":")[0] for m in models)
        return {
            "provider": self.name,
            "connected": True,
            "model": self.model,
            "model_available": model_available,
            "available_models": models[:20],
        }


class OpenAIProvider(LLMProvider):
    """OpenAI chat-completions provider (kept available for cloud mode)."""

    name = "openai"

    def __init__(self, api_key: str, model: str, timeout_seconds: float):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self.api_key, timeout=self.timeout_seconds)

    async def generate(self, prompt: str, system: str = "", max_tokens: int = 2000) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            response = await self._client().chat.completions.create(
                model=self.model, messages=messages, max_tokens=max_tokens
            )
        except Exception as e:
            raise LLMError(f"OpenAI request failed: {e}") from e
        return response.choices[0].message.content

    async def generate_json(self, prompt: str, system: str = "", max_tokens: int = 2000) -> dict:
        raw = await self.generate(prompt, system, max_tokens)
        return extract_json_object(raw)

    async def health_check(self) -> dict:
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        return {"provider": self.name, "connected": True, "model": self.model}


class AnthropicProvider(LLMProvider):
    """Anthropic messages provider (kept available for cloud mode)."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout_seconds: float):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _client(self):
        import anthropic

        return anthropic.AsyncAnthropic(api_key=self.api_key, timeout=self.timeout_seconds)

    async def generate(self, prompt: str, system: str = "", max_tokens: int = 2000) -> str:
        try:
            message = await self._client().messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise LLMError(f"Anthropic request failed: {e}") from e
        return message.content[0].text

    async def generate_json(self, prompt: str, system: str = "", max_tokens: int = 2000) -> dict:
        raw = await self.generate(prompt, system, max_tokens)
        return extract_json_object(raw)

    async def health_check(self) -> dict:
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        return {"provider": self.name, "connected": True, "model": self.model}


# ── Factory ───────────────────────────────────────────────────────────

_CLOUD_MODEL_DEFAULTS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
}


@lru_cache()
def get_llm_provider() -> LLMProvider:
    """Build the configured provider from settings (cached per process)."""
    settings = get_settings()
    provider_name = (settings.LLM_PROVIDER or "").strip().lower()
    timeout = float(settings.LLM_TIMEOUT_SECONDS)

    if provider_name == "ollama":
        return OllamaProvider(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            timeout_seconds=timeout,
        )

    if provider_name == "openai":
        if not settings.OPENAI_API_KEY:
            raise LLMError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL or _CLOUD_MODEL_DEFAULTS["openai"],
            timeout_seconds=timeout,
        )

    if provider_name == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise LLMError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_MODEL or _CLOUD_MODEL_DEFAULTS["anthropic"],
            timeout_seconds=timeout,
        )

    # Auto-detect (legacy behavior): first configured cloud key wins.
    if settings.ANTHROPIC_API_KEY:
        return AnthropicProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_MODEL or _CLOUD_MODEL_DEFAULTS["anthropic"],
            timeout_seconds=timeout,
        )
    if settings.OPENAI_API_KEY:
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL or _CLOUD_MODEL_DEFAULTS["openai"],
            timeout_seconds=timeout,
        )

    raise LLMError(
        "No LLM provider configured. Set LLM_PROVIDER=ollama (local, no key needed) "
        "or provide ANTHROPIC_API_KEY / OPENAI_API_KEY."
    )
