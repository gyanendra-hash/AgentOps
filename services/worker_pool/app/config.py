import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    redis_url: str
    scheduler_url: str
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    poll_timeout_seconds: float = 2.0
    service_name: str = "worker-pool"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        scheduler_url=os.environ.get("SCHEDULER_URL", "http://localhost:8002"),
        max_retries=int(os.environ.get("MAX_RETRIES", "3")),
        base_backoff_seconds=float(os.environ.get("BASE_BACKOFF_SECONDS", "1.0")),
        poll_timeout_seconds=float(os.environ.get("POLL_TIMEOUT_SECONDS", "2.0")),
    )
