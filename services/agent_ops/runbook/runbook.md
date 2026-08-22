# AgentOps On-Call Runbook

Ten scenarios an operator is likely to hit while running the AgentOps
platform (Rate Limiter, Gateway, Scheduler, Worker Pool), with symptoms,
likely causes, and fix steps. This is the document ingested by the Agentic AI
Ops Layer for RAG-grounded debugging (ROADMAP 3.2).

## Scenario: Gateway returning 503 for all requests

**Symptoms:** Every request through the Gateway returns `503 Service
Unavailable`, even for backends that are healthy.

**Likely causes:** The Rate Limiter is unreachable and `FAIL_OPEN=false`, so
the Gateway is rejecting everything instead of letting traffic through. Check
`docker compose ps` for the `rate-limiter` container's health status.

**Fix:** Restart the Rate Limiter service. If it needs to stay down for
maintenance, set `FAIL_OPEN=true` on the Gateway so it degrades to
unlimited-but-available instead of fully unavailable.

## Scenario: Rate limiter allowing more requests than the configured limit

**Symptoms:** A client with a configured limit of 20 requests/window is
getting more than 20 requests through.

**Likely causes:** Multiple Gateway replicas are running with rate-limit
state that isn't actually shared, or the Redis instance backing the limiter
was recently flushed/restarted and buckets reset to full capacity.

**Fix:** Confirm every Gateway/Rate-Limiter replica points at the same
`REDIS_URL`. Check Redis uptime — a restart resets all in-memory bucket
state, which is expected but should be rare in production.

## Scenario: Jobs stuck in PENDING forever

**Symptoms:** A submitted job never leaves `PENDING`, even after its
dependencies have `SUCCEEDED`.

**Likely causes:** No Scheduler replica currently holds leadership (all
replicas crashed, or the leader lock key was manually deleted from Redis
without a replica re-acquiring it), so nothing is running
`refresh_ready_jobs`.

**Fix:** Check Scheduler replica logs for leader-election activity. Confirm
at least one replica is running and can reach Redis. The leader lock
(`agentops:scheduler:leader`) should always have a live TTL; if it's missing
entirely, restart a Scheduler replica to re-acquire it.

## Scenario: Worker Pool not processing any jobs

**Symptoms:** Jobs reach `DISPATCHED` but never move to `RUNNING`.

**Likely causes:** The Worker Pool container is down, or it's connected to a
different Redis instance than the Scheduler is pushing jobs into.

**Fix:** Verify the Worker Pool's `REDIS_URL` matches the Scheduler's.
Check the Worker Pool container is running and its logs show it polling
(`BLPOP`) on the dispatch queue.

## Scenario: Dead-Letter Queue growing rapidly

**Symptoms:** `GET /v1/dlq` on the Worker Pool shows a fast-growing list of
failed jobs.

**Likely causes:** A downstream dependency the jobs rely on (e.g. an
external API) is down, so every attempt fails and every job exhausts its
retry budget in quick succession.

**Fix:** Inspect a few DLQ entries' `error` field for a common root cause.
Fix the downstream dependency, then re-drive the affected jobs (resubmit, or
a future agent tool call once Milestone 4 ships `list_failed_jobs` /
re-drive tooling).

## Scenario: Scheduler leader keeps flapping between replicas

**Symptoms:** Scheduler logs show leadership changing hands every few
seconds across replicas, and dispatch throughput drops.

**Likely causes:** `LEADER_TTL_SECONDS` is set too low relative to network
latency to Redis, so the current leader's renewal calls sometimes arrive
after the lock has already expired.

**Fix:** Increase `LEADER_TTL_SECONDS` (default 10s) so renewal has more
margin, or investigate Redis latency/network issues between the Scheduler
replicas and Redis.

## Scenario: Postgres connection pool exhausted

**Symptoms:** Scheduler or Worker Pool requests start timing out or erroring
with connection-pool-related messages under load.

**Likely causes:** `asyncpg.create_pool` was created with a `max_size` too
small for the current request concurrency, or a code path is acquiring a
connection and never releasing it (missing `async with`).

**Fix:** Check current pool `max_size` (default 10 per replica) against
concurrent request volume; increase it or scale out more replicas. Audit
recent code changes for connections acquired outside an `async with pool.acquire()` block.

## Scenario: Duplicate job dispatch (same job run twice)

**Symptoms:** The same job id shows two `RUNNING` executions, or downstream
side effects happened twice for one logical job.

**Likely causes:** Two Scheduler replicas both believed they were leader at
the same time — almost always caused by clock or network issues around
leader-lock renewal, not a bug in the dispatch-lock logic itself (which
already guards against double-pop within a single process).

**Fix:** Check Scheduler logs around the incident time for two replicas
both logging leader-election success close together. Confirm Redis wasn't
partitioned/split-brained during that window.

## Scenario: High latency on job dispatch under load

**Symptoms:** Jobs sit in `READY` for a long time before moving to
`DISPATCHED`, even though a leader is active and the queue isn't empty.

**Likely causes:** `DISPATCH_POLL_INTERVAL_SECONDS` is set too high, so the
Scheduler's dispatch loop only wakes up infrequently; or `find_ready_candidates`
is slow because the `jobs`/`job_dependencies` tables are large and missing
their indexes.

**Fix:** Lower `DISPATCH_POLL_INTERVAL_SECONDS` for tighter dispatch
latency. Confirm the `idx_jobs_status` and
`idx_job_dependencies_depends_on` indexes from the Scheduler's migration
actually exist (`\d jobs` in `psql`).
