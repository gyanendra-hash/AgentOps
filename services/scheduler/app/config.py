import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str
    redis_url: str
    service_name: str = "scheduler"
    leader_key: str = "agentops:scheduler:leader"
    leader_ttl_seconds: float = 10.0
    dispatch_poll_interval_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://agentops:agentops@localhost:5432/agentops"
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        leader_ttl_seconds=float(os.environ.get("LEADER_TTL_SECONDS", "10")),
        dispatch_poll_interval_seconds=float(
            os.environ.get("DISPATCH_POLL_INTERVAL_SECONDS", "1")
        ),
    )
