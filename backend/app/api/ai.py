"""AI endpoints: provider status, chat, and validated JSON generation.

All routes require authentication like the rest of the API.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import LLMError, get_llm_provider
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIHealthResponse,
    AIGenerateJSONRequest,
    AIGenerateJSONResponse,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/health", response_model=AIHealthResponse)
async def ai_health(user: User = Depends(get_current_user)):
    """Report which LLM provider is configured and whether it is reachable."""
    try:
        provider = get_llm_provider()
        detail = await provider.health_check()
        return AIHealthResponse(
            configured=True,
            provider=detail.get("provider", provider.name),
            model=detail.get("model"),
            connected=True,
            detail={k: v for k, v in detail.items() if k not in ("provider", "model")},
        )
    except LLMError as e:
        # Unreachable provider is a normal, reportable state — not a 500.
        return AIHealthResponse(
            configured=False,
            provider=get_settings().LLM_PROVIDER or "auto",
            model=None,
            connected=False,
            detail={"error": str(e)},
        )


@router.post("/chat", response_model=AIChatResponse)
async def ai_chat(
    payload: AIChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),  # noqa: ARG001 — keeps dependency graph consistent
):
    """Send a prompt to the configured LLM and return the raw completion."""
    try:
        provider = get_llm_provider()
        content = await provider.generate(payload.prompt, system=payload.system, max_tokens=payload.max_tokens)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return AIChatResponse(content=content, provider=provider.name)


@router.post("/generate-json", response_model=AIGenerateJSONResponse)
async def ai_generate_json(
    payload: AIGenerateJSONRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),  # noqa: ARG001 — keeps dependency graph consistent
):
    """Generate a validated JSON object from the configured LLM.

    The expected top-level keys can be enforced with `required_keys`; a
    response missing any of them fails with 502 and an explanatory message.
    """
    try:
        provider = get_llm_provider()
        data = await provider.generate_json(
            payload.prompt, system=payload.system, max_tokens=payload.max_tokens
        )
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e))

    missing = [k for k in payload.required_keys if k not in data]
    if missing:
        raise HTTPException(status_code=502, detail=f"LLM JSON missing required keys: {missing}")

    return AIGenerateJSONResponse(data=data, provider=provider.name)
