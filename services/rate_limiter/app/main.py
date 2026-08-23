from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis

from agentops_common.models import (
    RateLimitCheckRequest,
    RateLimitCheckResponse,
    RateLimitStatusResponse,
)
from app.algorithms import RateLimitResult, SlidingWindowLimiter, TokenBucketLimiter
from app.config import get_settings
from app.redis_client import get_redis

app = FastAPI(title="AgentOps Rate Limiter")

_token_bucket = TokenBucketLimiter()
_sliding_window = SlidingWindowLimiter()


def _bucket_key(client_id: str, tier_name: str) -> str:
    return f"ratelimit:{tier_name}:{client_id}"


async def _run_check(
    redis: Redis, client_id: str, tier_name: str, cost: int
) -> RateLimitResult:
    settings = get_settings()
    tier = settings.tiers.get(tier_name)
    if tier is None:
        raise HTTPException(status_code=404, detail=f"unknown tier: {tier_name}")

    key = _bucket_key(client_id, tier_name)
    if tier.algorithm == "token_bucket":
        return await _token_bucket.check(redis, key, tier, cost)
    if tier.algorithm == "sliding_window":
        return await _sliding_window.check(redis, key, tier, cost)
    raise HTTPException(status_code=500, detail=f"unsupported algorithm: {tier.algorithm}")


@app.post("/v1/rate-limit/check", response_model=RateLimitCheckResponse)
async def check_rate_limit(payload: RateLimitCheckRequest) -> RateLimitCheckResponse:
    settings = get_settings()
    tier = settings.tiers.get(payload.tier)
    if tier is None:
        raise HTTPException(status_code=404, detail=f"unknown tier: {payload.tier}")

    redis = get_redis()
    result = await _run_check(redis, payload.client_id, payload.tier, payload.cost)

    return RateLimitCheckResponse(
        allowed=result.allowed,
        algorithm=tier.algorithm,
        remaining=result.remaining,
        limit=result.limit,
        retry_after=result.retry_after,
    )


@app.get("/v1/rate-limit/status", response_model=RateLimitStatusResponse)
async def rate_limit_status(client_id: str, tier: str = "default") -> RateLimitStatusResponse:
    """Read-only status check for the Monitor Agent (Milestone 5) -- calls
    the same algorithm.check() as a real request, but with cost=0. Neither
    algorithm's Lua script consumes anything or changes remaining capacity
    at cost=0 (token bucket recomputes the refill and rewrites the same
    value; sliding window's INCRBY-by-0 is a no-op), so this never denies
    or spends a token on the caller's behalf."""
    settings = get_settings()
    tier_config = settings.tiers.get(tier)
    if tier_config is None:
        raise HTTPException(status_code=404, detail=f"unknown tier: {tier}")

    redis = get_redis()
    result = await _run_check(redis, client_id, tier, cost=0)

    return RateLimitStatusResponse(
        algorithm=tier_config.algorithm, remaining=result.remaining, limit=result.limit
    )


@app.get("/health")
async def health() -> dict:
    redis = get_redis()
    await redis.ping()
    return {"status": "ok"}
