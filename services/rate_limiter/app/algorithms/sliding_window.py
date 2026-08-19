from redis.asyncio import Redis

from app.algorithms.base import RateLimitResult
from app.config import TierConfig

SLIDING_WINDOW_SCRIPT = """
local prefix = KEYS[1]
local window_seconds = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])

local time_parts = redis.call('TIME')
local now = tonumber(time_parts[1]) + tonumber(time_parts[2]) / 1000000

local current_window = math.floor(now / window_seconds)
local previous_window = current_window - 1
local current_key = prefix .. ':' .. current_window
local previous_key = prefix .. ':' .. previous_window

local current_count = tonumber(redis.call('GET', current_key)) or 0
local previous_count = tonumber(redis.call('GET', previous_key)) or 0

local elapsed_in_current = now - (current_window * window_seconds)
local weight_previous = (window_seconds - elapsed_in_current) / window_seconds
if weight_previous < 0 then
    weight_previous = 0
end

local estimated = previous_count * weight_previous + current_count

local allowed = 0
if estimated + requested <= limit then
    current_count = redis.call('INCRBY', current_key, requested)
    redis.call('EXPIRE', current_key, window_seconds * 2)
    allowed = 1
    estimated = estimated + requested
end

local remaining = limit - estimated
if remaining < 0 then
    remaining = 0
end

return {allowed, tostring(remaining)}
"""


class SlidingWindowLimiter:
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
            self._script = redis.register_script(SLIDING_WINDOW_SCRIPT)

        window_seconds = tier.window_seconds
        limit = tier.limit

        allowed, remaining = await self._script(
            keys=[key],
            args=[window_seconds, limit, cost],
        )

        remaining_val = float(remaining)
        retry_after = None
        if not bool(int(allowed)):
            retry_after = window_seconds / max(limit, 1) if limit else window_seconds

        return RateLimitResult(
            allowed=bool(int(allowed)),
            remaining=remaining_val,
            limit=limit,
            retry_after=retry_after,
        )
