import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str
    redis_url: str
    service_name: str = "agent-ops"

    embedding_provider: str = "local"  # "local" (bge-small-en, no API key) | "openai"
    llm_provider: str = "openai"  # "openai" | "anthropic"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_model: str | None = None

    top_k: int = 5
    min_score: float = 0.3
    chunk_size: int = 500
    chunk_overlap: int = 50

    scheduler_url: str = "http://localhost:8002"
    confirmation_ttl_seconds: float = 300.0
    rate_limiter_url: str = "http://localhost:8001"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://agentops:agentops@localhost:5432/agentops"
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "local"),
        llm_provider=os.environ.get("LLM_PROVIDER", "openai"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        llm_model=os.environ.get("LLM_MODEL"),
        top_k=int(os.environ.get("RAG_TOP_K", "5")),
        min_score=float(os.environ.get("RAG_MIN_SCORE", "0.3")),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "500")),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", "50")),
        scheduler_url=os.environ.get("SCHEDULER_URL", "http://localhost:8002"),
        confirmation_ttl_seconds=float(os.environ.get("CONFIRMATION_TTL_SECONDS", "300")),
        rate_limiter_url=os.environ.get("RATE_LIMITER_URL", "http://localhost:8001"),
    )
