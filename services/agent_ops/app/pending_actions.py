"""Confirmation gate for destructive tools (ROADMAP 4.5, SRS FR-9). The
graph is invoked once per HTTP request, so "wait for confirmation" can't
mean pausing in-process -- instead a destructive decision is parked here
under a token and a *separate* request (POST /v1/agent/confirm) redeems it.
Redis-backed with a TTL so an abandoned confirmation doesn't linger
forever."""

import json
import uuid

from redis.asyncio import Redis

_KEY_PREFIX = "agentops:agent_ops:pending_action:"


class PendingActionStore:
    def __init__(self, redis: Redis, ttl_seconds: float) -> None:
        self._redis = redis
        # milliseconds, not whole seconds via `ex=` -- a sub-second
        # ttl_seconds (as used in tests) would otherwise truncate to 0,
        # which Redis treats as "already expired" instead of "never expires".
        self._ttl_ms = max(1, int(ttl_seconds * 1000))

    async def create(self, tool_name: str, args: dict, question: str) -> str:
        token = str(uuid.uuid4())
        payload = json.dumps({"tool_name": tool_name, "args": args, "question": question})
        await self._redis.set(f"{_KEY_PREFIX}{token}", payload, px=self._ttl_ms)
        return token

    async def get(self, token: str) -> dict | None:
        raw = await self._redis.get(f"{_KEY_PREFIX}{token}")
        return json.loads(raw) if raw else None

    async def delete(self, token: str) -> None:
        await self._redis.delete(f"{_KEY_PREFIX}{token}")
