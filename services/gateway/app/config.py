import json
import os
from functools import lru_cache

from pydantic import BaseModel


DEFAULT_ROUTING_TABLE: dict[str, list[str]] = {
    "backend": ["http://localhost:9000"],
}


class Settings(BaseModel):
    rate_limiter_url: str
    routing_table: dict[str, list[str]]
    default_service: str = "backend"
    default_tier: str = "default"
    fail_open: bool = True
    upstream_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    rate_limiter_url = os.environ.get(
        "RATE_LIMITER_URL", "http://localhost:8001"
    )
    raw_routing = os.environ.get("ROUTING_TABLE")
    routing_table = json.loads(raw_routing) if raw_routing else DEFAULT_ROUTING_TABLE
    fail_open = os.environ.get("FAIL_OPEN", "true").lower() == "true"

    return Settings(
        rate_limiter_url=rate_limiter_url,
        routing_table=routing_table,
        fail_open=fail_open,
    )
