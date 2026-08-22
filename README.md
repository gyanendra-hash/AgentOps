# AgentOps

Distributed API Gateway, Task Scheduler & Agentic AI Ops Layer.

A microservice platform combining a Redis-backed rate limiter, an API gateway, a
priority- and dependency-aware task scheduler, a worker pool, and a LangGraph-based
agentic control plane that can schedule jobs, answer operational questions, and debug
failures using RAG over system logs and runbooks.

Full requirements and design live in [docs/SRS.md](docs/SRS.md). Build status and
per-milestone checklists live in [ROADMAP.md](ROADMAP.md).

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
| [`services/agent_ops`](services/agent_ops) | NL control plane: routing, tool-calling, RAG debugging | PostgreSQL + pgvector, Redis | Milestones 3-6 |

Shared code (Pydantic models, Redis helpers) lives in
[`libs/agentops_common`](libs/agentops_common), imported by every service as an
editable local package so there's no duplicated logic between them.

## Quickstart

Requires Docker + Docker Compose. Copy the env template first:

```bash
cp .env.example .env
docker compose up --build
```

This brings up Redis, Postgres, the Rate Limiter, the Gateway, a dummy
backend, the Scheduler, and the Worker Pool. The Gateway listens on
`http://localhost:8080` and forwards `/api/*` to the dummy backend after a
rate-limit check.

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

All four services' tests run fully in-process against
[`fakeredis`](https://github.com/cunla/fakeredis-py), `respx`, and (for the
Scheduler) an in-memory fake of the Postgres repository — no Docker or
network access required. 71 tests currently pass (14 rate-limiter, 10
gateway, 34 scheduler, 13 worker-pool), including a rate-limiter concurrency
test that fires 50 parallel requests at a bucket of capacity 10 and asserts
exactly 10 are allowed, and a scheduler test that dispatches a 5-job DAG with
mixed priorities and asserts the exact dispatch order.

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
(`PENDING → READY → DISPATCHED → RUNNING → SUCCEEDED`, or `RETRY`/`DLQ` on
failure). `PATCH /v1/jobs/{id}/status` is how the Worker Pool reports
progress — the Scheduler is the only service that touches Postgres.

**Worker Pool** — has no public job API; it pulls from the Scheduler's Redis
dispatch queue and calls back into the Scheduler's `PATCH` endpoint. `GET
/v1/dlq` lists jobs that exhausted their retry budget, for manual or
agent-driven re-drive.

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

## Repository layout

```
AgentOps/
├── docs/                  SRS and design notes
├── infra/                 Redis config, other infra assets
├── libs/agentops_common/  Shared Pydantic models + Redis helpers
├── services/
│   ├── rate_limiter/      Milestone 1
│   ├── gateway/           Milestone 1
│   ├── dummy_backend/     Milestone 1 (test fixture service)
│   ├── service_registry/  Not started (Milestone 1 uses a static routing table)
│   ├── scheduler/         Milestone 2 (complete)
│   ├── worker_pool/       Milestone 2 (complete)
│   └── agent_ops/         Milestones 3-6
├── scripts/
│   ├── loadtest/          Locust load-test scripts
│   └── dev/               Local dev/test helper scripts
├── docker-compose.yml
└── ROADMAP.md             Milestone-by-milestone status
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full milestone breakdown and current status.
Milestones 1 (Rate Limiter + API Gateway) and 2 (Task Scheduler + Worker Pool)
are implemented and tested; later milestones are scaffolded with stub
services and will be filled in incrementally.
