"""Exponential backoff for job retries (ROADMAP 2.6). Pure functions, no I/O,
so they're trivially unit-testable."""


def next_backoff_seconds(attempt: int, base_seconds: float = 1.0, cap_seconds: float = 60.0) -> float:
    """`attempt` is 1-indexed (this is the Nth failure). Grows as
    base * 2**(attempt-1), capped so a flaky job doesn't end up parked for
    hours."""
    return min(cap_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def should_retry(attempt: int, max_retries: int) -> bool:
    return attempt < max_retries
