"""Redis-backed job dispatch queue shared by the scheduler (producer) and the
worker pool (consumer), so both services agree on key names and payload shape
without duplicating this logic."""

import json

from redis.asyncio import Redis

QUEUE_KEY = "agentops:jobs:queue"
DELAYED_KEY = "agentops:jobs:delayed"
DLQ_KEY = "agentops:jobs:dlq"


async def push_job(redis: Redis, job_id: str, payload: dict) -> None:
    await redis.rpush(QUEUE_KEY, json.dumps({"job_id": job_id, "payload": payload}))


async def pop_job(redis: Redis, timeout: float = 5.0) -> dict | None:
    result = await redis.blpop([QUEUE_KEY], timeout=timeout)
    if result is None:
        return None
    _, raw = result
    return json.loads(raw)


async def schedule_retry(redis: Redis, job_id: str, payload: dict, ready_at: float) -> None:
    """Park a failed job in a delayed set until `ready_at` (unix timestamp),
    instead of re-queuing it immediately, so exponential backoff actually
    delays the retry."""
    await redis.zadd(DELAYED_KEY, {json.dumps({"job_id": job_id, "payload": payload}): ready_at})


async def promote_due_retries(redis: Redis, now: float) -> int:
    """Move delayed jobs whose backoff has elapsed back onto the main queue.
    Workers should call this once per poll loop iteration before BLPOP."""
    due = await redis.zrangebyscore(DELAYED_KEY, min=0, max=now)
    promoted = 0
    for raw in due:
        removed = await redis.zrem(DELAYED_KEY, raw)
        if removed:
            await redis.rpush(QUEUE_KEY, raw)
            promoted += 1
    return promoted


async def push_dlq(redis: Redis, job_id: str, payload: dict, error: str) -> None:
    await redis.rpush(DLQ_KEY, json.dumps({"job_id": job_id, "payload": payload, "error": error}))


async def list_dlq(redis: Redis, limit: int = 100) -> list[dict]:
    raw_items = await redis.lrange(DLQ_KEY, 0, limit - 1)
    return [json.loads(item) for item in raw_items]
