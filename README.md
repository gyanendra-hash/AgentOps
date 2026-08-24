# AgentOps

Distributed API Gateway, Task Scheduler & Agentic AI Ops Layer.

A microservice platform combining a Redis-backed rate limiter, an API gateway, a
priority- and dependency-aware task scheduler, a worker pool, and a LangGraph-based
agentic control plane that classifies operator intent and routes it to a
scheduling agent, a RAG-grounded debugging agent, or a monitoring agent —
with per-node latency/token tracing and optional Langfuse export on every
agent call.

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
- [API reference (Milestone 5)](#api-reference-milestone-5)
- [Observability (Milestone 6)](#observability-milestone-6)
- [Design decisions](#design-decisions)
- [Repository layout](#repository-layout)
- [Branches](#branches)
- [Roadmap](#roadmap)

## Architecture

```
Client -> API Gateway -> Rate Limiter (Redis)
                       -> Service Registry (healthy instance lookup)
                       -> Backend Service -> Task Scheduler -> Worker Pool -> DLQ
Operator -> Agentic AI Ops Layer -> classify_intent -> Scheduler Agent  -> Scheduler API (tool calls)
                                                     -> Debug Agent     -> RAG Vector Store (pgvector)
                                                     -> Monitor Agent   -> Scheduler + Rate Limiter APIs
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
| [`services/agent_ops`](services/agent_ops) | RAG debugging, Scheduler tool-calling, intent-routed Monitor Agent, per-node tracing | PostgreSQL + pgvector, Redis | Milestone 6 |

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

Or skip deciding which endpoint to call yourself — `/v1/agent/ask` classifies
the request and routes it to whichever specialist applies:

```bash
curl -s -X POST http://localhost:8004/v1/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "how'\''s the queue looking right now?"}'
```

Every `/v1/agent/*` and `/v1/debug/ask` response includes a `trace` array —
per-node latency and (for LLM-calling nodes) token usage, with no setup
required. See [Observability (Milestone 6)](#observability-milestone-6).

Or run the whole walkthrough above in one go:

```bash
scripts/dev/demo.sh              # bash
scripts/dev/demo.ps1             # PowerShell

# no LLM key configured yet? skip Milestones 3-5 instead of erroring:
AGENT_OPS_HAS_LLM=0 scripts/dev/demo.sh
scripts/dev/demo.ps1 -SkipLLM
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
downloaded embedding model, and no LLM API key required. 174 tests currently
pass (17 rate-limiter, 10 gateway, 48 scheduler, 13 worker-pool, 86
agent-ops), including a rate-limiter concurrency test that fires 50 parallel
requests at a bucket of capacity 10 and asserts exactly 10 are allowed, a
scheduler test that dispatches a 5-job DAG with mixed priorities and asserts
the exact dispatch order, an agent-ops test that runs 10 sample debugging
questions through retrieval and checks each one is grounded in the right
runbook section, an agent-ops test that mocks a transient connection error
with `respx` and asserts the Scheduler tool call is retried and succeeds
rather than failing the whole request, an agent-ops end-to-end test that
routes 15 mixed schedule/debug/monitor/ambiguous queries and asserts 100%
reach the correct specialist, and an agent-ops test that runs two graph
invocations concurrently with separate tracers and asserts neither sees the
other's spans (a regression test for a real bug caught while building
Milestone 6 — see [Observability (Milestone 6)](#observability-milestone-6)).

`services/agent_ops/scripts/run_eval.py` is the one script in this repo
meant to make a real LLM call rather than run against a fake — it drives the
20-query eval set (ROADMAP 6.3/6.4) through a live, configured
`classify_intent` once `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` is set, and
prints routing accuracy plus any misclassified questions.

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

`GET /v1/rate-limit/status?client_id=acme&tier=default` (added in Milestone
5, for the Monitor Agent) reports current remaining/limit without spending a
request — a read-only peek, not a check.

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

`GET /v1/jobs/stats` (added in Milestone 5, for the Monitor Agent) returns
job counts per status, e.g. `{"counts": {"PENDING": 3, "DLQ": 1}}` — queue
depth without fetching every job record.

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

## API reference (Milestone 5)

**Agent Ops** — `POST /v1/agent/ask` is the unified entry point: one call
classifies intent (`schedule` / `debug` / `monitor` / `ambiguous`) and
routes to whichever specialist applies.

```json
{"question": "why is the gateway returning 503?"}
```

routes to the same debug/RAG graph `/v1/debug/ask` uses and returns
`{"response": "...", "result": null, ...}`; a scheduling request routes to
the same Scheduler Agent `/v1/agent/schedule` uses (destructive tools still
return `needs_confirmation`); a monitoring request

```json
{"question": "what's client acme's current rate limit usage?"}
```

routes to the Monitor Agent and returns queue depth and/or rate-limit status
in `result`. A request that doesn't clearly fit any category gets a
clarifying question back instead of a guess:

```json
{"response": "I'm not sure whether you want to schedule something, debug an issue, or check system status -- could you clarify?"}
```

`GET /v1/monitor/status?client_id=acme&tier=default` reaches the Monitor
Agent directly, with **no LLM call** — `client_id` is optional (omit it to
get queue depth only). Useful for a dashboard or health check that
shouldn't depend on LLM availability/latency to render.

`/v1/debug/ask` and `/v1/agent/schedule` from Milestones 3/4 keep working
unchanged, for callers that already know which specialist they want and
would rather skip the classification call.

## Observability (Milestone 6)

Every `/v1/debug/ask`, `/v1/agent/schedule`, and `/v1/agent/ask` response
includes a `trace` array — no configuration needed:

```json
{
  "trace": [
    {"node": "retrieve", "latency_ms": 12.4, "usage": null},
    {"node": "rerank", "latency_ms": 45.1, "usage": null},
    {"node": "generate", "latency_ms": 812.7, "usage": {"prompt_tokens": 512, "completion_tokens": 84}}
  ]
}
```

Setting `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` (`LANGFUSE_HOST` too,
for self-hosted Langfuse) additionally exports each request as a trace in
[Langfuse](https://langfuse.com) with the same per-node spans and token
usage — this is strictly additive; leaving them unset costs nothing, breaks
nothing, and the `trace` field in the API response is unaffected either way.

**Evaluation** — `services/agent_ops/eval/eval_set.py` has 20 questions
covering all four intents plus a few genuinely ambiguous ones. Run it for
real once an LLM key is configured:

```bash
cd services/agent_ops
python scripts/run_eval.py
```

```
Accuracy: 95% (19/20)

Failures:
  - 'what happened to job-1 yesterday': expected 'ambiguous', got 'schedule'
```

Doesn't need Postgres/Redis/the Scheduler/the Rate Limiter running — it
calls `classify_intent` directly rather than executing whichever specialist
it routes to, since ROADMAP 6.4 asks specifically for *routing* accuracy.
`tests/test_eval.py` covers the harness itself (accuracy math, failure
capture) against a fake classifier, the same way every other LLM boundary
in this repo is tested.

**Confirmation timeout** — a `cancel_job` confirmation
(`CONFIRMATION_TTL_SECONDS`, default 300s) that's never confirmed or
declined simply expires; redeeming an expired or unknown token returns "That
confirmation has expired or was already used" rather than an error.

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
- **The orchestrator routes into existing graphs; it doesn't reimplement
  them.** `run_scheduler_agent`/`run_debug_agent` in `app/orchestrator.py`
  call the exact same compiled graphs `/v1/agent/schedule` and
  `/v1/debug/ask` use, via a plain `ainvoke()` — a routing node calling a
  sub-graph as a function, not nested `StateGraph` composition. Simpler, and
  the two graphs' state schemas never had to be unified into one.
- **Monitor Agent needs no tool-calling LLM of its own.** Unlike the
  Scheduler Agent, there's no ambiguity in *which* tool to run once intent
  is `monitor` — queue depth is always fetched, and rate-limit status is
  fetched if (and only if) `classify_intent` extracted a `client_id`. One
  structured-output call (classification + entity extraction together)
  covers it; a second LLM round-trip would just add latency for no
  additional decision being made.
- **`classify_intent`'s extraction is one-shot, with no self-correction
  loop.** If it mis-extracts a `client_id` from an ambiguous request, the
  Monitor Agent just reports whatever it extracted rather than asking a
  follow-up question -- see the Known Limitation in ROADMAP.md Milestone 5.
  A `clarify`-and-retry loop here would mirror Milestone 4's confirmation
  gate, but queue-depth-only monitoring (no client_id) never needs it, so
  it's deferred rather than speculatively built.
- **`GET /v1/rate-limit/status` reuses `check()` at `cost=0`, not a new Lua
  script.** Both algorithms' scripts are no-ops (or a same-value rewrite) at
  `cost=0` -- confirmed by `test_status_does_not_consume_a_token` -- so a
  second read-only script would have been duplicated logic for no behavioral
  difference.
- **A `Tracer` lives in graph *state*, never in a node closure.** Every
  LangGraph here is compiled once at startup and reused across every
  concurrent request; a tracer captured in a node's closure at build time
  would silently accumulate every request's spans into one shared,
  ever-growing list. Each node instead reads `state["tracer"]`, set fresh
  per `ainvoke()` call -- this was a real bug caught while building
  Milestone 6, not a hypothetical one; see
  `test_concurrent_graph_invocations_get_isolated_traces`.
- **Local trace collection is unconditional; Langfuse export is optional on
  top of it.** `Tracer` always runs and is always returned in the API
  response's `trace` field -- ROADMAP 6.2 doesn't depend on ROADMAP 6.1.
  `LangfuseExporter` is a separate, additional destination for the same
  data, a no-op unless `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` are set.
- **The eval script measures routing, not execution.** `run_eval` calls
  `IntentClassifier.classify()` directly rather than invoking the full
  orchestrator graph, so `scripts/run_eval.py` only needs an LLM key -- not
  a running Scheduler/Rate-Limiter/Postgres/Redis -- to produce a
  meaningful accuracy number, matching what ROADMAP 6.4 actually asks for.
- **`PendingActionStore` sets Redis TTL in milliseconds (`PX`), not whole
  seconds (`EX`).** Building the Milestone 6 test suite surfaced a real bug:
  `EX` truncates any `ttl_seconds < 1` to `0`, which Redis treats as
  "expire immediately" rather than "never expires" -- harmless at the
  default 300s, but would have silently broken a short TTL used for
  testing or a fast-confirmation deployment. Fixed and covered by
  `test_confirmation_expires_after_ttl_elapses`.

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
│   └── agent_ops/         Milestone 6 (complete) -- every milestone done
├── scripts/
│   ├── loadtest/          Locust load-test scripts
│   └── dev/               Local dev/test helper scripts (test_all.sh / .ps1 / demo.sh / demo.ps1)
├── .env.example           Template for a local .env (copy before `docker compose up`)
├── docker-compose.yml     Redis, Postgres (+pgvector), and every service, wired together
└── ROADMAP.md             Milestone-by-milestone status
```

Every `services/*` entry other than `dummy_backend` follows the same
internal shape: `app/` (FastAPI app + business logic), `tests/` (pytest,
mocks only — no Docker required), `Dockerfile`, `requirements.txt` /
`requirements-dev.txt`, and `pytest.ini`. `scheduler/` and `agent_ops/`
additionally have a `migrations/` folder of raw SQL run at startup;
`agent_ops/` also has `runbook/runbook.md` (the document it ingests for RAG)
and `eval/` + `scripts/run_eval.py` (the Milestone 6 evaluation set/runner).

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

See [ROADMAP.md](ROADMAP.md) for the full milestone breakdown and current
status. All six milestones — Rate Limiter + API Gateway, Task Scheduler +
Worker Pool, RAG Q&A, Tool-Calling, Multi-Agent Routing, and Guardrails +
Observability — are implemented and tested. 174 tests pass without any
external dependency; `services/agent_ops/scripts/run_eval.py` is the one
additional check that needs a real `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` to
run.
