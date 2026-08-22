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

- [ ] 3.1 — pgvector extension + embeddings table
- [ ] 3.2 — Sample runbook covering 5-10 failure scenarios
- [ ] 3.3 — Ingestion script: chunk + embed + store
- [ ] 3.4 — Standalone top-k retrieval function
- [ ] 3.5 — Single LangGraph node: question → retrieve → grounded answer
- [ ] 3.6 — Manual test with 10 sample debugging questions
- [ ] 3.7 — Cross-encoder reranking step
- [ ] 3.8 — Bug-fix pass: chunk size/overlap tuning, irrelevant-chunk filtering

**Status: not started.**

## Milestone 4 — Agentic AI: Tool-Calling

- [ ] 4.1 — Pydantic tool schemas (`create_job`, `cancel_job`, `get_job_status`, `list_failed_jobs`)
- [ ] 4.2 — Tool functions wrapping Gateway/Scheduler REST endpoints
- [ ] 4.3 — Scheduler Agent node in LangGraph
- [ ] 4.4 — NL request correctly calls `create_job` with right arguments
- [ ] 4.5 — Confirmation guardrail for destructive tools via a clarify node
- [ ] 4.6 — Bug-fix pass: malformed args, API timeouts, retry-on-tool-failure

**Status: not started.**

## Milestone 5 — Multi-Agent Routing

- [ ] 5.1 — `classify_intent` node
- [ ] 5.2 — Conditional edges to Scheduler / Debug / Monitor agents
- [ ] 5.3 — Monitor Agent (rate-limit status, queue depth)
- [ ] 5.4 — Clarify node for ambiguous intent
- [ ] 5.5 — End-to-end test: 15 mixed queries, routing accuracy measured
- [ ] 5.6 — Bug-fix pass: misclassified cases, few-shot examples

**Status: not started.**

## Milestone 6 — Guardrails + Observability (Production-readiness)

- [ ] 6.1 — Langfuse SDK integration
- [ ] 6.2 — Per-node latency and token-cost tracking
- [ ] 6.3 — 20-query evaluation set
- [ ] 6.4 — Eval run, routing/tool-call accuracy measured, failures logged
- [ ] 6.5 — Confirmation-flow hardening (timeout on unconfirmed destructive action)
- [ ] 6.6 — Final bug-fix/polish pass, README + demo script

**Status: not started.**
