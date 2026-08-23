# AgentOps

Distributed API Gateway, Task Scheduler & Agentic AI Ops Layer.

A microservice platform combining a Redis-backed rate limiter, an API gateway, a
priority- and dependency-aware task scheduler, a worker pool, and a LangGraph-based
agentic control plane that can schedule jobs, answer operational questions, and debug
failures using RAG over system logs and runbooks.

Full requirements and design live in [docs/SRS.md](docs/SRS.md). Build status and
per-milestone checklists live in [ROADMAP.md](ROADMAP.md).

- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [Local development (without Docker)](#local-development-without-docker)
- [Running tests](#running-tests)
- [Load testing](#load-testing)
- [API reference (Milestone 1)](#api-reference-milestone-1)
- [API reference (Milestone 2)](#api-reference-milestone-2)
- [API reference (Milestone 3)](#api-reference-milestone-3)
- [API reference (Milestone 4)](#api-reference-milestone-4)
- [Design decisions](#design-decisions)
- [Repository layout](#repository-layout)
- [Branches](#branches)
- [Roadmap](#roadmap)

## Architecture

```
Client -> API Gateway -> Rate Limiter (Redis)
                       -> Service Registry (healthy instance lookup)
                       -> Backend Service -> Task Scheduler -> Worker Pool -> DLQ
Operator -> Agentic AI Ops Layer -> Gateway/Scheduler APIs (tool calls)
                                  -> RAG Vector Store (pgvector)
```

Six independently deployable services, each owning its own data:

| Service | Responsibility | Data Store | Status |
|---|---|---|---|
| [`services/rate_limiter`](services/rate_limiter) | Token Bucket / Sliding Window limit checks | Redis | Milestone 1 |
| [`services/gateway`](services/gateway) | Routing, edge rate-limit enforcement, service discovery | Stateless | Milestone 1 |
| [`services/dummy_backend`](services/dummy_backend) | Test backend used by the Gateway during local dev/load tests | Stateless | Milestone 1 |
| [`services/service_registry`](services/service_registry) | Track healthy service instances | Redis (TTL keys) | Not started — Milestone 1 ships with a static routing table instead |
| [`services/scheduler`](services/scheduler) | Priority + dependency-aware job dispatch, leader election | PostgreSQL, Redis | Milestone 2 |
| [`services/worker_pool`](services/worker_pool) | Execute jobs, retry, DLQ | Redis (calls Scheduler API for job state) | Milestone 2 |
| [`services/agent_ops`](services/agent_ops) | RAG-grounded debugging + Scheduler tool-calling; multi-agent routing from Milestone 5 | PostgreSQL + pgvector, Redis | Milestone 4 |

Shared code (Pydantic models, Redis helpers) lives in
[`libs/agentops_common`](libs/agentops_common), imported by every service as an
editable local package so there's no duplicated logic between them.

## Quickstart

Requires Docker + Docker Compose. Copy the env template first:

```bash
cp .env.example .env
docker compose up --build
```

This brings up Redis, Postgres (with pgvector), the Rate Limiter, the
Gateway, a dummy backend, the Scheduler, the Worker Pool, and Agent Ops. The
Gateway listens on `http://localhost:8080` and forwards `/api/*` to the
dummy backend after a rate-limit check.

```bash
curl -i http://localhost:8080/api/ping -H "X-Client-Id: demo"
```

Repeat quickly enough and you'll get `429 Too Many Requests` with a
`Retry-After` header once the configured limit is exceeded.

Submit a small job DAG to the Scheduler and watch the Worker Pool run it:

```bash
curl -s -X POST http://localhost:8002/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"jobs":[{"ref":"a","name":"extract","priority":5},{"ref":"b","name":"load","priority":1,"depends_on":["a"]}]}'
```

`b` stays `PENDING` until `a` reaches `SUCCEEDED`; poll either job with
`GET /v1/jobs/{id}`.

Ask the Agent Ops service a debugging question grounded in the bundled
runbook (needs `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` set in `.env` first —
see [API reference (Milestone 3)](#api-reference-milestone-3)):

```bash
curl -s -X POST http://localhost:8004/v1/debug/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "the dead letter queue is growing fast, what should I check?"}'
```

Ask it to act on the Scheduler instead of just answering — non-destructive
tools run immediately, `cancel_job` asks for confirmation first:

```bash
curl -s -X POST http://localhost:8004/v1/agent/schedule \
  -H "Content-Type: application/json" \
  -d '{"question": "create a job called nightly-etl with priority 5"}'

curl -s -X POST http://localhost:8004/v1/agent/schedule \
  -H "Content-Type: application/json" \
  -d '{"question": "cancel job <job-id>"}'
# -> {"needs_confirmation": true, "confirmation_token": "...", ...}

curl -s -X POST http://localhost:8004/v1/agent/confirm \
  -H "Content-Type: application/json" \
  -d '{"confirmation_token": "<token from above>", "confirmed": true}'
```

## Local development (without Docker)

Each service is a standalone FastAPI app with its own `requirements.txt`. From a
service directory:

```bash
cd services/rate_limiter        # or services/gateway
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt -e ../../libs/agentops_common
uvicorn app.main:app --reload --port 8001
```

## Running tests

```bash
scripts/dev/test_all.sh          # bash
scripts/dev/test_all.ps1         # PowerShell
```

Or per-service:

```bash
cd services/rate_limiter
pip install -r requirements.txt -r requirements-dev.txt -e ../../libs/agentops_common
PYTHONPATH=. pytest -v
```

All five services' tests run fully in-process against
[`fakeredis`](https://github.com/cunla/fakeredis-py), [`respx`](https://github.com/lundberg/respx),
and in-memory fakes of the Postgres/pgvector repositories — no Docker, no
downloaded embedding model, and no LLM API key required. 132 tests currently
pass (14 rate-limiter, 10 gateway, 44 scheduler, 13 worker-pool, 51
agent-ops), including a rate-limiter concurrency test that fires 50 parallel
requests at a bucket of capacity 10 and asserts exactly 10 are allowed, a
scheduler test that dispatches a 5-job DAG with mixed priorities and asserts
the exact dispatch order, an agent-ops test that runs 10 sample debugging
questions through retrieval and checks each one is grounded in the right
runbook section, and an agent-ops test that mocks a transient connection
error with `respx` and asserts the Scheduler tool call is retried and
succeeds rather than failing the whole request.

`services/agent_ops/requirements.txt` pulls in `sentence-transformers`
(for the self-hosted embedding + reranking models) and `torch` as a
transitive dependency — installing it is noticeably slower than the other
services' dependencies, but none of it is required to actually *run* the
tests, since they exercise fakes behind the same provider interfaces the
real implementations use.

## Load testing

```bash
pip install locust
locust -f scripts/loadtest/locustfile.py --host http://localhost:8080
```

## API reference (Milestone 1)

**Rate Limiter** — `POST /v1/rate-limit/check`

```json
{"client_id": "acme", "tier": "default", "cost": 1}
```

```json
{"allowed": true, "algorithm": "token_bucket", "remaining": 19, "limit": 20, "retry_after": null}
```

Tiers and their algorithm/parameters are configured via the `RATE_LIMIT_TIERS`
env var (JSON), defaulting to a `default` tier on Token Bucket (capacity 20,
refill 5/sec) and a `premium` tier on Sliding Window (limit 200 per 60s).

**Gateway** — any method under `/api/{path}` is proxied to the configured
`backend` service after a rate-limit check keyed by the `X-Client-Id` header
(falls back to the caller's IP). Denied requests get `429` with a
`Retry-After` header; an unreachable backend returns `503`.

## API reference (Milestone 2)

**Scheduler** — `POST /v1/jobs` submits a batch of jobs sharing one DAG. Each
job has a client-chosen `ref` (unique within the batch) so later jobs in the
same call can declare dependencies before those dependencies have a database
id yet:

```json
{
  "jobs": [
    {"ref": "extract", "name": "extract", "priority": 5},
    {"ref": "load", "name": "load", "priority": 1, "depends_on": ["extract"]}
  ]
}
```

A batch whose dependencies form a cycle is rejected whole with `422` before
anything is written. `GET /v1/jobs/{id}` returns current status
(`PENDING → READY → DISPATCHED → RUNNING → SUCCEEDED`, or `RETRY`/`DLQ`/`CANCELLED`
on failure/cancellation). `GET /v1/jobs?status=DLQ` lists jobs, optionally
filtered by status. `POST /v1/jobs/{id}/cancel` cancels a job that hasn't
been dispatched yet (`PENDING`/`READY`/`RETRY`); once a worker may already
be running it, cancellation is refused with `409` rather than racing the
Worker Pool. `PATCH /v1/jobs/{id}/status` is how the Worker Pool reports
progress — the Scheduler is the only service that touches Postgres.

**Worker Pool** — has no public job API; it pulls from the Scheduler's Redis
dispatch queue and calls back into the Scheduler's `PATCH` endpoint. `GET
/v1/dlq` lists jobs that exhausted their retry budget, for manual or
agent-driven re-drive.

## API reference (Milestone 3)

**Agent Ops** — `POST /v1/debug/ask`:

```json
{"question": "why is the gateway returning 503 for every request?"}
```

```json
{
  "answer": "The Rate Limiter is unreachable and FAIL_OPEN=false, so the Gateway is rejecting everything...",
  "sources": ["runbook"]
}
```

On first boot, the service ingests the bundled
[`runbook/runbook.md`](services/agent_ops/runbook/runbook.md) (10 on-call
scenarios) if the `embeddings` table is empty — no separate ingestion step
needed for the demo. Retrieval drops any chunk scoring below `RAG_MIN_SCORE`
(default `0.3`); if everything gets filtered out, the answer is "I don't
have enough information" instead of a hallucinated guess. `GET /health`
checks the process is up (it doesn't touch Postgres or the LLM).

This endpoint needs a real LLM key to answer for real —
`OPENAI_API_KEY` (default) or `ANTHROPIC_API_KEY` with
`LLM_PROVIDER=anthropic`. Embeddings default to the self-hosted
`bge-small-en` (`EMBEDDING_PROVIDER=local`, no key needed); switch to
`EMBEDDING_PROVIDER=openai` for `text-embedding-3-small` instead.

## API reference (Milestone 4)

**Agent Ops** — `POST /v1/agent/schedule` decides which Scheduler tool (if
any) applies to a natural-language request and either runs it or asks for
confirmation:

```json
{"question": "create a job called nightly-etl with priority 5"}
```

```json
{"response": "Ran `create_job` successfully. Result: {...}", "needs_confirmation": false, "confirmation_token": null, "result": {"id": "...", "name": "nightly-etl", ...}}
```

Four tools: `create_job`, `get_job_status`, `list_failed_jobs` (all
non-destructive, run immediately) and `cancel_job` (destructive — returns
`needs_confirmation: true` and a `confirmation_token` instead of executing):

```json
{"response": "About to run `cancel_job` (...) with arguments {\"job_id\": \"...\"}. Confirm?", "needs_confirmation": true, "confirmation_token": "8f1e...", "result": null}
```

`POST /v1/agent/confirm {"confirmation_token": "...", "confirmed": true}`
redeems it and actually cancels the job; `"confirmed": false` (or letting
the token expire after `CONFIRMATION_TTL_SECONDS`, default 300s) discards it
with no effect. If no tool matches the request, or a tool call fails
(unknown job id, job already dispatched, Scheduler unreachable), `response`
explains why instead of the request failing with a 500.

This endpoint needs the same LLM key as Milestone 3's `/v1/debug/ask`
(`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) — one call decides *whether* to
call a tool and *which* tool, via the provider's native function-calling.

## Design decisions

- **Atomicity via Lua, not read-modify-write.** Both algorithms run as a
  single Redis `EVAL` script so the check-and-decrement is atomic — this is
  what the concurrency tests actually verify (50 concurrent requests against a
  bucket of 10 never allow more than 10).
- **Clock skew.** The Lua scripts read time from Redis's own `TIME` command
  instead of trusting each Gateway/Rate-Limiter replica's system clock, so
  limits stay correct even if replica clocks drift.
- **Fail-open by default.** If the Gateway can't reach the Rate Limiter, it
  lets the request through rather than returning 503 for everything —
  availability of the core path is prioritized over strict limit enforcement,
  matching the NFR that the Gateway/Rate-Limiter path targets 99.9% uptime.
  This is a deliberate trade-off, not an oversight; flip it per-deployment via
  `FAIL_OPEN=false`.
- **No Service Registry yet.** Milestone 1 forwards to a static routing table
  (`ROUTING_TABLE` env var) instead of building the Service Registry service.
  This is faithful to SRS step 1.5 ("static routing table") — dynamic
  discovery is future work once there's more than one backend to discover.
- **Repository abstraction over Postgres, mirroring fakeredis.** The
  Scheduler talks to storage through a `JobRepository` protocol; tests run
  against an in-memory fake instead of a real Postgres instance
  (`services/scheduler/tests/fakes.py`), the same trade-off Milestone 1 makes
  by testing against fakeredis. `PostgresJobRepository` (asyncpg) is the real
  implementation used in Docker Compose.
- **Cycle rejection happens once, at submission.** Kahn's algorithm runs over
  the client-supplied batch before anything is written; once accepted,
  dispatch-time readiness is a plain SQL "all dependencies SUCCEEDED" check
  (`find_ready_candidates`), so the live job table never needs a topological
  sort of its own.
- **Only the elected leader dispatches.** `LeaderElection` uses `SET key val
  NX PX ttl` to acquire and a Lua compare-and-swap to renew/release, so a
  crashed leader's lock simply expires rather than needing another replica to
  detect the crash explicitly.
- **The Worker Pool never touches Postgres.** It calls the Scheduler's
  `PATCH /v1/jobs/{id}/status` instead, so the Scheduler stays the single
  owner of job state (SRS: "each service owns its data") and the Worker Pool
  only needs Redis + an HTTP client.
- **Retries are delayed, not immediate.** A failed job goes into a Redis
  sorted set keyed by its backoff-computed ready time
  (`agentops_common/queue.py::schedule_retry`) instead of being re-queued
  immediately; each worker poll promotes only the entries whose delay has
  elapsed, so exponential backoff actually delays the retry instead of just
  labeling it.
- **Every RAG stage is a swappable interface, tested with a fake.**
  `EmbeddingProvider`, `Reranker`, and `AnswerGenerator` are each a
  `Protocol` with a real (model/API-backed) implementation and a fake used
  in tests — the same repository-abstraction pattern as the Scheduler, so
  the retrieve → rerank → generate pipeline is fully unit-tested without a
  downloaded model, Postgres, or an LLM API key.
- **Cross-encoder reranking only runs on the top-k, not the whole corpus.**
  A cross-encoder scores each `(query, chunk)` pair jointly and is far more
  accurate than the initial vector search, but too slow to run over every
  stored chunk — it only re-scores the handful of candidates vector search
  already narrowed down to.
- **Irrelevant context is dropped, not force-fed to the LLM.** Retrieval
  filters out anything scoring below `RAG_MIN_SCORE` (ROADMAP 3.8); if
  nothing clears the bar, the answer is an explicit "I don't have enough
  information" instead of the LLM being handed unrelated chunks and asked
  to make something up anyway.
- **Answer generation has no self-hosted fallback, by design.** Embeddings
  and reranking both default to self-hosted models specifically so a fresh
  checkout can ingest and retrieve without any API key; the final answer
  still needs a real LLM call (SRS 9: "OpenAI gpt-4o-mini or Claude API"),
  since there's no local model in the stack (Ollama is called out in SRS 10
  as a stretch goal, not a v1 requirement).
- **The single LangGraph node is one node on purpose, not a shortcut.**
  SRS 6.5.1's full graph (`classify_intent -> route -> {scheduler_agent |
  debug_agent | monitor_agent} -> clarify -> respond`) has no branching to
  justify until intent classification exists (Milestone 5) — `answer_question`
  in `app/graph.py` is written to become the `debug_agent` node in that
  larger graph, not to be rewritten from scratch.
- **Confirmation is a second HTTP request, not a paused graph.** A LangGraph
  run completes within one request; there's no in-process way to "wait" for
  a human across requests. `clarify` instead parks the decision in Redis
  under a token and ends the graph — `POST /v1/agent/confirm` is a
  completely separate invocation that redeems it. This is the same shape
  production agent APIs generally use for human-in-the-loop steps.
- **Tools wrap REST endpoints; they never touch Postgres.** Per SRS 6.5.4
  ("the agent never re-implements scheduling logic"), `list_failed_jobs` and
  `cancel_job` needed two new Scheduler endpoints (`GET /v1/jobs`,
  `POST /v1/jobs/{id}/cancel`) rather than having Agent Ops query the jobs
  table directly — the Scheduler stays the only service that owns job state.
- **The LLM's tool-call decision is the one thing tests can't verify for
  real.** `ToolCallingLLM` is a `Protocol` like `AnswerGenerator`; tests
  preprogram `FakeToolCallingLLM` with the decision a real LLM *would*
  plausibly return for a given request, then verify everything downstream —
  argument validation, tool dispatch, the confirmation gate, retry-on-failure
  — actually behaves correctly. Whether the LLM parses a given sentence into
  the *right* tool call is a prompt/model quality question, not a plumbing
  one, and needs a real API key to evaluate.
- **`SchedulerClient` retries once, not indefinitely.** A single retry on
  `httpx.TransportError` (connection reset, DNS blip) covers the common
  transient case without turning a genuinely-down Scheduler into a long hang
  for whoever's waiting on the agent's HTTP response.

## Repository layout

```
AgentOps/
├── docs/
│   └── SRS.md             Full requirements + per-milestone low-level design
├── libs/agentops_common/  Shared Pydantic models + Redis queue/DLQ helpers
├── services/
│   ├── rate_limiter/      Milestone 1 (complete)
│   ├── gateway/           Milestone 1 (complete)
│   ├── dummy_backend/     Milestone 1 (test fixture service)
│   ├── service_registry/  Not started (Milestone 1 uses a static routing table)
│   ├── scheduler/         Milestone 2 (complete)
│   ├── worker_pool/       Milestone 2 (complete)
│   └── agent_ops/         Milestone 4 (complete); multi-agent routing from Milestone 5
├── scripts/
│   ├── loadtest/          Locust load-test scripts
│   └── dev/               Local dev/test helper scripts (test_all.sh / .ps1)
├── .env.example           Template for a local .env (copy before `docker compose up`)
├── docker-compose.yml     Redis, Postgres (+pgvector), and every service, wired together
└── ROADMAP.md             Milestone-by-milestone status
```

Every `services/*` entry other than `dummy_backend` follows the same
internal shape: `app/` (FastAPI app + business logic), `tests/` (pytest,
mocks only — no Docker required), `Dockerfile`, `requirements.txt` /
`requirements-dev.txt`, and `pytest.ini`. `scheduler/` and `agent_ops/`
additionally have a `migrations/` folder of raw SQL run at startup;
`agent_ops/` also has `runbook/runbook.md`, the document it ingests for RAG.

## Branches

| Branch | Purpose |
|---|---|
| `main` | Current, deployable state of the whole repo — both milestones merged in |
| `stage` | Staging environment target |
| `dev` | Active development target |
| `prod` | Production deployment target |
| `milestone-1-rate-limiter-gateway` | Kept as a historical snapshot of Milestone 1 in isolation |

`main`, `stage`, `dev`, and `prod` currently point at the same commit; they
diverge as work lands on `dev`, gets promoted to `stage` for verification,
and finally to `prod`. `milestone-1-rate-limiter-gateway` is not part of that
flow — it's a frozen reference branch, kept for history rather than
continued development.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full milestone breakdown and current status.
Milestones 1 (Rate Limiter + API Gateway), 2 (Task Scheduler + Worker Pool),
3 (RAG Q&A), and 4 (Tool-Calling) are implemented and tested; multi-agent
routing (Milestone 5) and observability/guardrails (Milestone 6) are not
started yet.
