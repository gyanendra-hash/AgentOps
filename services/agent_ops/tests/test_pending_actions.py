"""ROADMAP 6.5: confirmation-flow hardening -- a destructive action's
confirmation must not linger forever if the operator never confirms it.
`PendingActionStore` relies on Redis's own key TTL rather than a manual
sweep, so expiry here doubles as a test that the TTL is actually being set
correctly (not just accepted and ignored)."""

import asyncio

from app.pending_actions import PendingActionStore


async def test_create_returns_a_redeemable_token(redis_client):
    store = PendingActionStore(redis_client, ttl_seconds=300)

    token = await store.create("cancel_job", {"job_id": "job-1"}, "cancel job job-1")
    pending = await store.get(token)

    assert pending == {"tool_name": "cancel_job", "args": {"job_id": "job-1"}, "question": "cancel job job-1"}


async def test_delete_makes_the_token_unredeemable(redis_client):
    store = PendingActionStore(redis_client, ttl_seconds=300)
    token = await store.create("cancel_job", {"job_id": "job-1"}, "cancel job job-1")

    await store.delete(token)

    assert await store.get(token) is None


async def test_unknown_token_returns_none(redis_client):
    store = PendingActionStore(redis_client, ttl_seconds=300)

    assert await store.get("never-existed") is None


async def test_confirmation_expires_after_ttl_elapses(redis_client):
    """A destructive action's confirmation window is bounded -- an operator
    who never responds doesn't leave a stale action redeemable indefinitely."""
    store = PendingActionStore(redis_client, ttl_seconds=0.1)
    token = await store.create("cancel_job", {"job_id": "job-1"}, "cancel job job-1")

    assert await store.get(token) is not None  # still valid immediately after creation

    await asyncio.sleep(0.2)

    assert await store.get(token) is None  # expired -- Redis dropped the key itself
