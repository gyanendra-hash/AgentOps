from redis.asyncio import Redis

from app.algorithms.base import RateLimitResult
from app.config import TierConfig

TOKEN_BUCKET_SCRIPT = """
local bucket_key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl_seconds = tonumber(ARGV[4])

local time_parts = redis.call('TIME')
local now = tonumber(time_parts[1]) + tonumber(time_parts[2]) / 1000000

local state = redis.call('HMGET', bucket_key, 'tokens', 'last_refill')
local tokens = tonumber(state[1])
local last_refill = tonumber(state[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

local elapsed = now - last_refill
if elapsed < 0 then
    elapsed = 0
end
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
local retry_after = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    local deficit = requested - tokens
    retry_after = deficit / refill_rate
end

redis.call('HMSET', bucket_key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
redis.call('EXPIRE', bucket_key, ttl_seconds)

return {allowed, tostring(tokens), tostring(retry_after)}
"""


class TokenBucketLimiter:
    def __init__(self) -> None:
        self._script = None

    async def check(
        self,
        redis: Redis,
        key: str,
        tier: TierConfig,
        cost: int,
    ) -> RateLimitResult:
        if self._script is None:
            self._script = redis.register_script(TOKEN_BUCKET_SCRIPT)

        capacity = tier.capacity
        refill_rate = tier.refill_rate
        ttl_seconds = max(60, int(capacity / refill_rate) + 60)

        allowed, tokens, retry_after = await self._script(
            keys=[key],
            args=[capacity, refill_rate, cost, ttl_seconds],
        )

        return RateLimitResult(
            allowed=bool(int(allowed)),
            remaining=float(tokens),
            limit=capacity,
            retry_after=float(retry_after) if float(retry_after) > 0 else None,
        )
