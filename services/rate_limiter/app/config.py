import json
import os
from functools import lru_cache

from pydantic import BaseModel


class TierConfig(BaseModel):
    algorithm: str
    capacity: float | None = None
    refill_rate: float | None = None
    limit: float | None = None
    window_seconds: float | None = None


DEFAULT_TIERS: dict[str, dict] = {
    "default": {"algorithm": "token_bucket", "capacity": 20, "refill_rate": 5},
    "premium": {"algorithm": "sliding_window", "limit": 200, "window_seconds": 60},
}


class Settings(BaseModel):
    redis_url: str
    tiers: dict[str, TierConfig]
    service_name: str = "rate-limiter"


@lru_cache
def get_settings() -> Settings:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    raw_tiers = os.environ.get("RATE_LIMIT_TIERS")
    tiers_dict = json.loads(raw_tiers) if raw_tiers else DEFAULT_TIERS
    tiers = {name: TierConfig(**cfg) for name, cfg in tiers_dict.items()}
    return Settings(redis_url=redis_url, tiers=tiers)
