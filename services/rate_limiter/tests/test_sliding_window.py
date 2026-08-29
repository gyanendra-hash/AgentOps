import asyncio

from app.algorithms.sliding_window import SlidingWindowLimiter
from app.config import TierConfig


async def test_allows_up_to_limit(redis_client):
    tier = TierConfig(algorithm="sliding_window", limit=3, window_seconds=2)
    limiter = SlidingWindowLimiter()

    results = [
        await limiter.check(redis_client, "sw:a", tier, 1) for _ in range(3)
    ]

    assert all(r.allowed for r in results)


async def test_denies_beyond_limit_within_window(redis_client):
    tier = TierConfig(algorithm="sliding_window", limit=2, window_seconds=2)
    limiter = SlidingWindowLimiter()

    for _ in range(2):
        await limiter.check(redis_client, "sw:b", tier, 1)

    result = await limiter.check(redis_client, "sw:b", tier, 1)

    assert result.allowed is False
    assert result.retry_after is not None


async def test_window_slides_after_time_passes(redis_client):
    tier = TierConfig(algorithm="sliding_window", limit=2, window_seconds=1)
    limiter = SlidingWindowLimiter()

    for _ in range(2):
        await limiter.check(redis_client, "sw:c", tier, 1)

    denied = await limiter.check(redis_client, "sw:c", tier, 1)
    assert denied.allowed is False

    # The weighted sliding-window estimate keeps decaying the previous
    # window's count until a full window has elapsed since crossing into a
    # new one, so a full 2 window-lengths must pass (worst case: the
    # original requests landed right at the start of their window) before
    # the previous window is guaranteed to no longer contribute.
    await asyncio.sleep(2 * tier.window_seconds + 0.1)

    allowed_again = await limiter.check(redis_client, "sw:c", tier, 1)
    assert allowed_again.allowed is True


async def test_concurrent_requests_never_over_allow(redis_client):
    limit = 10
    tier = TierConfig(algorithm="sliding_window", limit=limit, window_seconds=5)
    limiter = SlidingWindowLimiter()

    results = await asyncio.gather(
        *(limiter.check(redis_client, "sw:concurrent", tier, 1) for _ in range(50))
    )

    allowed_count = sum(1 for r in results if r.allowed)
    assert allowed_count == limit
