from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis

from agentops_common.models import RateLimitCheckRequest, RateLimitCheckResponse
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


@app.get("/health")
async def health() -> dict:
    redis = get_redis()
    await redis.ping()
    return {"status": "ok"}
