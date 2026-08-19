import asyncio

from app.algorithms.token_bucket import TokenBucketLimiter
from app.config import TierConfig


async def test_allows_up_to_capacity(redis_client):
    tier = TierConfig(algorithm="token_bucket", capacity=3, refill_rate=1)
    limiter = TokenBucketLimiter()

    results = [await limiter.check(redis_client, "client:a", tier, 1) for _ in range(3)]

    assert all(r.allowed for r in results)


async def test_denies_beyond_capacity(redis_client):
    tier = TierConfig(algorithm="token_bucket", capacity=2, refill_rate=1)
    limiter = TokenBucketLimiter()

    for _ in range(2):
        await limiter.check(redis_client, "client:b", tier, 1)

    result = await limiter.check(redis_client, "client:b", tier, 1)

    assert result.allowed is False
    assert result.retry_after is not None
    assert result.retry_after > 0


async def test_refills_over_time(redis_client):
    tier = TierConfig(algorithm="token_bucket", capacity=1, refill_rate=20)
    limiter = TokenBucketLimiter()

    first = await limiter.check(redis_client, "client:c", tier, 1)
    assert first.allowed is True

    denied = await limiter.check(redis_client, "client:c", tier, 1)
    assert denied.allowed is False

    await asyncio.sleep(0.15)

    refilled = await limiter.check(redis_client, "client:c", tier, 1)
    assert refilled.allowed is True


async def test_cost_greater_than_one(redis_client):
    tier = TierConfig(algorithm="token_bucket", capacity=5, refill_rate=1)
    limiter = TokenBucketLimiter()

    result = await limiter.check(redis_client, "client:d", tier, 5)
    assert result.allowed is True
    assert result.remaining == 0

    result = await limiter.check(redis_client, "client:d", tier, 1)
    assert result.allowed is False


async def test_independent_clients_have_separate_buckets(redis_client):
    tier = TierConfig(algorithm="token_bucket", capacity=1, refill_rate=0.001)
    limiter = TokenBucketLimiter()

    result_a = await limiter.check(redis_client, "client:e", tier, 1)
    result_b = await limiter.check(redis_client, "client:f", tier, 1)

    assert result_a.allowed is True
    assert result_b.allowed is True


async def test_concurrent_requests_never_over_allow(redis_client):
    capacity = 10
    tier = TierConfig(algorithm="token_bucket", capacity=capacity, refill_rate=0.001)
    limiter = TokenBucketLimiter()

    results = await asyncio.gather(
        *(limiter.check(redis_client, "client:concurrent", tier, 1) for _ in range(50))
    )

    allowed_count = sum(1 for r in results if r.allowed)
    assert allowed_count == capacity
