from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AI Job Application Copilot"
    APP_URL: str = "http://localhost:3000"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/jobcopilot"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/jobcopilot"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ALGORITHM: str = "HS256"

    # LLM
    # LLM_PROVIDER: "ollama" (local, no key needed) | "openai" | "anthropic".
    # Leave empty for legacy auto-detect (first configured cloud key wins).
    LLM_PROVIDER: str = ""
    LLM_TIMEOUT_SECONDS: float = 120.0
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Embeddings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384

    # Job Board APIs
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    if not settings.DEBUG and settings.SECRET_KEY in ("", "change-me-in-production", "change-me-in-production-use-openssl-rand-hex-32"):
        raise RuntimeError(
            "SECRET_KEY must be set to a strong random value when DEBUG=false. "
            "Generate one with: openssl rand -hex 32"
        )
    return settings
