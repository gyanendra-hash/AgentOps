"""Monitor Agent (ROADMAP 5.3): reports queue depth (always) and a specific
client's rate-limit status (if a client_id was extracted from the request).
No LLM call of its own -- which tool to run isn't ambiguous the way
Scheduler tool selection is, since there's only ever one thing to check per
piece of information available. The intent classifier (app/intent.py)
extracts `client_id`/`tier` as part of its single structured-output call."""

from app.rate_limiter_client import RateLimiterClient, RateLimiterUnavailableError
from app.scheduler_client import SchedulerClient, SchedulerUnavailableError


async def run_monitor(
    scheduler_client: SchedulerClient,
    rate_limiter_client: RateLimiterClient,
    *,
    client_id: str | None = None,
    tier: str = "default",
) -> tuple[str, dict]:
    """Returns (response_text, data). `data` always has "queue_depth"; it
    has "rate_limit" too if `client_id` was given and the Rate Limiter
    answered."""
    data: dict = {}
    lines = []

    try:
        queue_depth = await scheduler_client.queue_depth()
        data["queue_depth"] = queue_depth
        total = sum(queue_depth.values())
        lines.append(f"Queue depth: {total} jobs total ({queue_depth})" if queue_depth else "Queue depth: 0 jobs")
    except SchedulerUnavailableError as exc:
        lines.append(f"Queue depth: unavailable ({exc})")

    if client_id:
        try:
            status = await rate_limiter_client.status(client_id, tier)
            data["rate_limit"] = status
            lines.append(
                f"Rate limit for '{client_id}' ({tier}): {status['remaining']:.1f}/{status['limit']:.0f} remaining"
            )
        except RateLimiterUnavailableError as exc:
            lines.append(f"Rate limit for '{client_id}': unavailable ({exc})")

    return " | ".join(lines), data
