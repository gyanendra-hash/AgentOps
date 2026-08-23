# Roadmap

Status tracker for the milestone plan defined in [docs/SRS.md](docs/SRS.md) section 8.
Checked items are implemented and covered by passing tests.

## Milestone 1 — Rate Limiter + API Gateway (Foundation)

- [x] 1.1 — Repo structure, Docker Compose skeleton, Redis container
- [x] 1.2 — Token Bucket algorithm, unit tested
- [x] 1.3 — Token Bucket state in Redis via an atomic Lua script; concurrency test confirms no over-allowance
- [x] 1.4 — Sliding Window Counter as a second, config-selectable algorithm
- [x] 1.5 — Minimal Gateway: static routing table, forwards to a dummy backend
- [x] 1.6 — Rate Limiter wired into the Gateway's request path (allow/deny + 429 + `Retry-After`)
- [x] 1.7 — Locust load-test script (`scripts/loadtest/locustfile.py`)
- [x] 1.8 — Bug-fix pass: clock skew (Redis server `TIME`, not client clock), burst traffic (concurrency tests), multiple Gateway instances sharing one Redis (stateless Gateway, all limiter state lives in Redis)

**Status: complete.** 24 tests passing (`services/rate_limiter`: 14, `services/gateway`: 10).

**Deliverable:** Gateway correctly allows/denies requests under concurrent load, verified by test — see [services/rate_limiter/tests](services/rate_limiter/tests) and [services/gateway/tests](services/gateway/tests).

## Milestone 2 — Task Scheduler + Worker Pool

- [x] 2.1 — Job schema + Postgres migration (`services/scheduler/migrations/001_create_jobs.sql`)
- [x] 2.2 — In-memory Min-Heap priority queue (`services/scheduler/app/heap.py`)
- [x] 2.3 — DAG dependency model + topological sort (Kahn's algorithm), cycle rejection (`services/scheduler/app/dag.py`)
- [x] 2.4 — Persist queue state to Redis (`libs/agentops_common/agentops_common/queue.py`)
- [x] 2.5 — Basic Worker Pool: pull job, execute mock task, update status (`services/worker_pool/app/worker.py`)
- [x] 2.6 — Retry with exponential backoff + Dead-Letter Queue (`services/worker_pool/app/retry.py`, `agentops_common/queue.py`)
- [x] 2.7 — Leader election (Redis `SETNX` + TTL), tested with 2+ replicas (`services/scheduler/app/leader_election.py`)
- [x] 2.8 — Integration test: 5-job DAG, mixed priorities, correct dispatch order (`test_five_job_dag_mixed_priorities_dispatch_order`)
- [x] 2.9 — Bug-fix pass: concurrent pop races (`test_concurrent_dispatch_next_never_double_dispatches`), TTL-expiry edge cases (`test_expired_lock_lets_another_replica_take_over`), starvation checks (`test_older_equal_priority_job_not_starved_by_newer_arrivals`)

**Status: complete.** 47 tests passing (`services/scheduler`: 34, `services/worker_pool`: 13), on top of the 24 from Milestone 1.

**Deliverable:** submit a batch of jobs with priorities and dependencies via
`POST /v1/jobs`; the leader-elected Scheduler replica resolves the DAG,
dispatches READY jobs in priority order over Redis, and the Worker Pool
executes them with exponential-backoff retries and a Dead-Letter Queue for
exhausted jobs — see
[services/scheduler/tests](services/scheduler/tests) and
[services/worker_pool/tests](services/worker_pool/tests).

**Known limitation carried into a later pass:** the ready-queue heap only
prevents starvation *within* a priority tier (FIFO); a continuous stream of
higher-priority jobs can still starve a lower-priority tier indefinitely.
Priority aging isn't implemented.

## Milestone 3 — Agentic AI: RAG Q&A (no tool-calling yet)

- [x] 3.1 — pgvector extension + embeddings table (`services/agent_ops/migrations/001_create_embeddings.sql`)
- [x] 3.2 — Sample runbook covering 5-10 failure scenarios (`services/agent_ops/runbook/runbook.md`, 10 scenarios)
- [x] 3.3 — Ingestion script: chunk + embed + store (`services/agent_ops/app/ingest.py`)
- [x] 3.4 — Standalone top-k retrieval function (`services/agent_ops/app/retrieval.py::retrieve`)
- [x] 3.5 — Single LangGraph node: question → retrieve → grounded answer (`services/agent_ops/app/graph.py`)
- [x] 3.6 — Manual test with 10 sample debugging questions (`test_question_retrieves_grounded_context`, automated — one parametrized case per question instead of a one-off manual check)
- [x] 3.7 — Cross-encoder reranking step (`services/agent_ops/app/reranker.py::CrossEncoderReranker`)
- [x] 3.8 — Bug-fix pass: `min_score` cutoff drops irrelevant chunks instead of forcing them into context (`test_min_score_filters_out_irrelevant_context`); chunk size/overlap tunable via `CHUNK_SIZE`/`CHUNK_OVERLAP`

**Status: complete.** 97 tests passing (14 rate-limiter, 10 gateway, 34
scheduler, 13 worker-pool, 26 agent-ops).

**Deliverable:** `POST /v1/debug/ask {"question": "..."}` on the Agent Ops
service returns an answer grounded in the ingested runbook, plus its
`sources`. Retrieval, reranking, and answer generation all sit behind
provider interfaces (`EmbeddingProvider`, `Reranker`, `AnswerGenerator`), so
the full pipeline is unit-tested with fakes — no Postgres, no downloaded
model, no LLM API key required to run the test suite. Real deployment needs
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` for answer generation; embeddings
default to the self-hosted `bge-small-en` (no key needed) but can switch to
`text-embedding-3-small` via `EMBEDDING_PROVIDER=openai`.

**Known limitation carried into a later pass:** the LangGraph here is a
single node with no branching — that's intentional for this milestone (see
`app/graph.py`), but it means there's no `classify_intent`/`clarify` routing
yet. Every question is treated as a debugging question; non-debugging
queries just get "I don't have enough information" once nothing scores
above `RAG_MIN_SCORE`. Multi-intent routing is Milestone 5.

## Milestone 4 — Agentic AI: Tool-Calling

- [x] 4.1 — Pydantic tool schemas (`create_job`, `cancel_job`, `get_job_status`, `list_failed_jobs`) — `services/agent_ops/app/tools.py`
- [x] 4.2 — Tool functions wrapping Scheduler REST endpoints — `services/agent_ops/app/scheduler_client.py`. Two new Scheduler endpoints (`GET /v1/jobs`, `POST /v1/jobs/{id}/cancel`) were added so `list_failed_jobs`/`cancel_job` wrap something real instead of being faked
- [x] 4.3 — Scheduler Agent node in LangGraph — `services/agent_ops/app/scheduler_agent.py`, the first *branching* graph in the repo (`decide_tool -> clarify | execute_tool -> respond`)
- [x] 4.4 — NL request correctly calls `create_job` with right arguments (`test_nl_request_calls_create_job_with_right_arguments`)
- [x] 4.5 — Confirmation guardrail for destructive tools via a `clarify` node (`test_destructive_tool_requires_confirmation_and_does_not_execute`, `test_confirming_a_pending_cancel_executes_it`)
- [x] 4.6 — Bug-fix pass: malformed args (`InvalidToolArgsError` → friendly message, not a crash), API timeouts/connection errors (`SchedulerClient` retries once, then a friendly "scheduler unavailable" message), retry-on-tool-failure (`test_transient_failure_is_retried_once`)

**Status: complete.** 132 tests passing (14 rate-limiter, 10 gateway, 44
scheduler, 13 worker-pool, 51 agent-ops).

**Deliverable:** `POST /v1/agent/schedule {"question": "..."}` decides which
Scheduler tool applies (if any) and either runs it immediately
(`create_job`, `get_job_status`, `list_failed_jobs`) or — for the one
destructive tool, `cancel_job` — returns `needs_confirmation: true` with a
`confirmation_token` instead of executing. `POST /v1/agent/confirm
{"confirmation_token": "...", "confirmed": true}` redeems it. Tool-call
decisions come from a real LLM's function-calling (`OPENAI_API_KEY` or
`ANTHROPIC_API_KEY`, same as Milestone 3); tests preprogram the decision via
a fake so the routing/confirmation/retry plumbing is verified without an
LLM call — see [services/agent_ops/tests](services/agent_ops/tests).

**Known limitation carried into a later pass:** confirmation state lives in
Redis with a TTL (`CONFIRMATION_TTL_SECONDS`, default 300s) rather than a
durable store — an abandoned confirmation just expires, which is correct
behavior, but a Redis flush mid-flow would silently drop a pending
confirmation too. Acceptable for now since destructive actions require
confirmation either way (silent execution isn't possible), but worth
revisiting if confirmations need to survive a Redis restart.

## Milestone 5 — Multi-Agent Routing

- [x] 5.1 — `classify_intent` node — `services/agent_ops/app/intent.py`, one structured-output call returning `{intent, client_id, tier}`
- [x] 5.2 — Conditional edges to Scheduler / Debug / Monitor agents — `services/agent_ops/app/orchestrator.py`, routing the Milestone 3/4 graphs in as sub-nodes rather than rebuilding them
- [x] 5.3 — Monitor Agent (rate-limit status, queue depth) — `services/agent_ops/app/monitor_agent.py`. Needed two new endpoints: Rate Limiter's `GET /v1/rate-limit/status` (read-only peek, doesn't consume a request) and Scheduler's `GET /v1/jobs/stats` (counts per status)
- [x] 5.4 — Clarify node for ambiguous intent — `clarify_intent` node in `orchestrator.py` (distinct from Milestone 4's destructive-action `clarify` — this one asks the operator to rephrase, not to confirm)
- [x] 5.5 — End-to-end test: 15 mixed queries, routing accuracy measured — `test_15_mixed_queries_route_to_the_correct_specialist`, asserts 100% of a representative schedule/debug/monitor/ambiguous mix reaches the correct specialist
- [x] 5.6 — Bug-fix pass: misclassified cases (`_coerce` falls back to `ambiguous` on an out-of-schema response instead of raising), few-shot examples (added to `intent.py`'s system prompt after "how's the queue looking" was initially misrouted to `debug`)

**Status: complete.** 157 tests passing (17 rate-limiter, 10 gateway, 48
scheduler, 13 worker-pool, 69 agent-ops).

**Deliverable:** `POST /v1/agent/ask {"question": "..."}` is now the single
entry point — it classifies intent and routes to whichever specialist
applies, falling back to a clarifying question when it can't tell.
`GET /v1/monitor/status` gives deterministic, no-LLM access to the same
Monitor Agent data for dashboards/health checks that shouldn't depend on an
LLM call. `/v1/debug/ask` and `/v1/agent/schedule` (Milestones 3/4) still
work directly, for callers that already know which specialist they want.

**Known limitation carried into a later pass:** the Monitor Agent's
`client_id`/`tier` extraction depends entirely on `classify_intent` pulling
them out correctly in one shot; there's no fallback question or clarify step
if a monitor-intent request names a client ambiguously (e.g. two similar
client ids in one sentence). Acceptable given the queue-depth half of
monitoring never needs a client_id at all; worth revisiting if per-client
monitoring becomes a primary use case.

## Milestone 6 — Guardrails + Observability (Production-readiness)

- [ ] 6.1 — Langfuse SDK integration
- [ ] 6.2 — Per-node latency and token-cost tracking
- [ ] 6.3 — 20-query evaluation set
- [ ] 6.4 — Eval run, routing/tool-call accuracy measured, failures logged
- [ ] 6.5 — Confirmation-flow hardening (timeout on unconfirmed destructive action)
- [ ] 6.6 — Final bug-fix/polish pass, README + demo script

**Status: not started.**
