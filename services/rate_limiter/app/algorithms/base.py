from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

from app.config import TierConfig


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float
    limit: float
    retry_after: float | None


class RateLimiterAlgorithm(Protocol):
    async def check(
        self,
        redis: Redis,
        key: str,
        tier: TierConfig,
        cost: int,
    ) -> RateLimitResult: ...
