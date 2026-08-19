# Software Requirements Specification

**AgentOps: Distributed API Gateway, Task Scheduler & Agentic AI Ops Layer**

Version 1.0 · Author: Gyanendra Pratap Singh · Date: August 2026

Transcribed from the original SRS PDF for in-repo reference. This is the source of
truth for design decisions; [ROADMAP.md](../ROADMAP.md) tracks implementation status
against it.

## 1. Introduction

### 1.1 Purpose

This document specifies the functional and non-functional requirements, high-level
design (HLD), low-level design (LLD), and development roadmap for AgentOps — a
microservice platform combining a Distributed Rate Limiter, API Gateway, Job
Scheduler, Worker Pool, and an Agentic AI Ops layer. It is intended to serve as the
single reference for design decisions, data-structure choices, and phased
implementation.

### 1.2 Scope

AgentOps provides:

- Traffic control at the edge via a distributed, Redis-backed rate limiter and API Gateway.
- Reliable asynchronous job execution via a priority- and dependency-aware Task Scheduler and Worker Pool.
- A conversational, agentic control plane (LangGraph multi-agent system) that can schedule jobs, answer operational questions, and debug failures using Retrieval-Augmented Generation (RAG) over system logs.

Out of scope for v1: multi-region deployment, a user-facing web dashboard
(CLI/API only), and billing/metering.

### 1.3 Definitions & Abbreviations

| Term | Meaning |
|---|---|
| HLD | High-Level Design — system architecture and component interaction |
| LLD | Low-Level Design — internal algorithms, data structures, and class/module design |
| DAG | Directed Acyclic Graph — used for job dependency resolution and agent orchestration |
| RAG | Retrieval-Augmented Generation — grounding LLM output in retrieved documents |
| DLQ | Dead-Letter Queue — holds jobs that failed after max retries |
| SLA | Service Level Agreement — target latency/availability guarantees |

## 2. Overall System Description

### 2.1 Product Perspective

AgentOps is a standalone microservice platform, deployable via Docker Compose,
composed of six independently scalable services: API Gateway, Rate Limiter, Task
Scheduler, Worker Pool, Service Registry, and the Agentic AI Ops layer. Each service
owns its data and communicates over well-defined internal APIs (REST/gRPC).

### 2.2 System Features (Summary)

- F1 — Distributed rate limiting per client/API key
- F2 — Request routing with dynamic service discovery
- F3 — Priority- and dependency-aware job scheduling
- F4 — Fault-tolerant asynchronous job execution with retries
- F5 — Natural-language operational control via AI agents
- F6 — RAG-grounded debugging and monitoring over logs/incidents

### 2.3 User Classes

| User Class | Description |
|---|---|
| API Consumer | External client/service sending rate-limited requests through the Gateway |
| Job Producer | Internal service/user submitting jobs to the Scheduler |
| Operator | Engineer interacting with the Agentic AI Ops layer to schedule, monitor, or debug |

### 2.4 Operating Environment

- Containerized via Docker; orchestrated with Docker Compose (v1) / Kubernetes-ready (future)
- Python 3.11+, FastAPI for all service APIs
- PostgreSQL (with pgvector extension) for durable state and embeddings
- Redis for distributed counters, queues, and short-term agent memory

## 3. High-Level Design (HLD)

### 3.1 Architecture Overview

Client requests enter through the API Gateway, which consults the Rate Limiter
before routing to backend services via the Service Registry. Job-oriented requests
are handed to the Task Scheduler, which dispatches to the Worker Pool. The Agentic
AI Ops layer sits alongside as a control-plane service: it calls the same
Gateway/Scheduler APIs a human operator would, and separately queries a RAG index
built from logs and runbooks.

#### 3.1.1 Component Interaction (textual flow)

1. Client → API Gateway (request arrives)
2. API Gateway → Rate Limiter (`check_limit(client_id)`)
3. API Gateway → Service Registry (resolve healthy backend instance)
4. API Gateway → Backend Service (forward request)
5. Backend Service → Task Scheduler (submit job, if applicable)
6. Task Scheduler → Worker Pool (dispatch job per priority/dependency order)
7. Worker Pool → Retry Queue / DLQ (on failure, after max attempts)
8. Operator → Agentic AI Ops Layer (natural-language request)
9. Agentic AI Ops Layer → Gateway/Scheduler APIs (tool calls) and/or RAG Vector Store (context retrieval)

### 3.2 Service Responsibilities

| Service | Responsibility | Data Store |
|---|---|---|
| API Gateway | Routing, edge rate-limit enforcement, service discovery lookup | Stateless (reads Redis + Registry) |
| Rate Limiter | Token Bucket / Sliding Window limit checks | Redis |
| Service Registry | Track healthy service instances | Redis (TTL keys) or etcd |
| Task Scheduler | Priority + dependency-aware job dispatch, leader election | PostgreSQL (job metadata), Redis (queue) |
| Worker Pool | Execute jobs, retry on failure, push to DLQ | PostgreSQL (job status), Redis (queue) |
| Agentic AI Ops Layer | NL control plane: routing, tool-calling, RAG debugging | PostgreSQL + pgvector, Redis (session state) |

### 3.3 Scalability & Reliability Strategy

- Gateway and Worker Pool scale horizontally behind the Service Registry; no shared in-process state.
- Redis Cluster (or single-node for v1) backs rate-limit counters so limits stay consistent across N Gateway replicas.
- Scheduler leader election (Redis `SETNX` + TTL, or Redlock) ensures only one instance dispatches jobs at a time, preventing duplicate execution.
- Worker failures are isolated per-job via retry + DLQ; one bad job never blocks the queue.

## 4. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | System shall enforce per-client rate limits using a configurable algorithm (Token Bucket or Sliding Window). | High |
| FR-2 | System shall route incoming requests to healthy backend instances via dynamic service discovery. | High |
| FR-3 | System shall allow job submission with a priority and optional dependency list (DAG). | High |
| FR-4 | System shall dispatch jobs in dependency-safe, priority order. | High |
| FR-5 | System shall retry failed jobs up to N times before moving them to a Dead-Letter Queue. | High |
| FR-6 | System shall guarantee exactly-once job dispatch even with multiple Scheduler replicas. | High |
| FR-7 | System shall accept natural-language operator requests and classify intent (schedule / debug / monitor). | High |
| FR-8 | System shall answer debugging questions grounded in retrieved logs/runbooks (RAG), not from model memory alone. | High |
| FR-9 | System shall require explicit confirmation before executing destructive agent actions (e.g., bulk job cancellation). | High |
| FR-10 | System shall trace every agent run (nodes visited, tools called, latency, token cost) for observability. | Medium |

## 5. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Latency | Rate-limit check adds < 5ms p99 at the Gateway; agent intent-classification responds < 2s p95. |
| Scalability | Gateway and Worker Pool must scale horizontally to 10x baseline load without code changes. |
| Availability | Core Gateway + Rate Limiter path targets 99.9% uptime; single Scheduler replica failure must not cause missed dispatches. |
| Consistency | Rate-limit counters must be consistent across all Gateway replicas (no double-allowance under concurrent requests). |
| Security | All internal service-to-service calls authenticated (JWT or mTLS); destructive agent tools require confirmation. |
| Observability | Every request traceable end-to-end via correlation IDs; agent runs traced via Langfuse. |
| Maintainability | Each service independently deployable and testable; no shared mutable state between services. |

## 6. Low-Level Design (LLD)

### 6.1 Rate Limiter

Two interchangeable algorithms, selectable per client tier:

- **Token Bucket** — bucket of capacity C, refilled at rate R tokens/sec. Each request consumes 1 token; request denied if bucket is empty. O(1) check using a Redis hash storing `{tokens, last_refill_timestamp}`.
- **Sliding Window Counter** — hybrid of fixed-window counters weighted by overlap fraction, approximates a true sliding log at O(1) space per client instead of O(n) requests.

DSA mapping:

- Sliding Window pattern → weighted counter windows
- Circular Buffer → bounded in-memory request timestamp log at the Gateway edge (avoids unbounded memory growth per client)
- Queue → per-client request timestamp queue for the exact sliding-log variant, when strict accuracy is required over performance

Complexity: O(1) time per check for Token Bucket and windowed-counter Sliding
Window; O(k) for exact sliding-log where k = requests in window (bounded by rate
limit itself, so effectively small).

### 6.2 API Gateway

- Routing table: Hashmap of `{service_name → [instance_urls]}`, refreshed from Service Registry every T seconds (or via pub/sub invalidation).
- Load balancing across instances: Round-robin (v1) or Consistent Hashing (v2) — consistent hashing minimizes re-routing churn when instances scale up/down, important once the Worker Pool auto-scales.
- DSA mapping: Hashmap (O(1) routing lookup), Consistent Hashing ring (O(log N) instance lookup, minimal remapping on topology change).

### 6.3 Task Scheduler

Core data structures:

- Min-Heap (Priority Queue) keyed by `(priority, scheduled_time)` — O(log n) insert/pop for next-job-to-run.
- DAG (adjacency list) for job dependencies — job B holds a list of prerequisite job IDs; Scheduler performs a Topological Sort (Kahn's algorithm, O(V+E)) to compute a valid dispatch order and detect dependency cycles at submission time (reject cyclic DAGs).
- Leader Election: Redis `SETNX` with TTL renewal (simple v1) or Redlock across N Redis nodes (v2) — only the elected leader pops from the heap and dispatches, eliminating duplicate dispatch races.

Job state machine: `PENDING → READY (dependencies satisfied) → DISPATCHED →
RUNNING → SUCCEEDED / FAILED → (RETRY → RUNNING) or (DLQ)`.

### 6.4 Worker Pool

- Workers pull from a Redis-backed queue (Redis Streams or List with `BLPOP`) — Queue DSA pattern, FIFO per priority tier.
- Retry policy: exponential backoff (`base × 2^attempt`, capped), attempt counter stored with the job record.
- Dead-Letter Queue: separate Redis list/stream; jobs here require manual or agent-triggered re-drive.

### 6.5 Agentic AI Ops Layer

#### 6.5.1 Agent Graph (LangGraph) — HLD within the layer

Nodes: `classify_intent → route → {scheduler_agent | debug_agent |
monitor_agent} → clarify (if ambiguous) → respond`. Edges are conditional, based
on the `classify_intent` output; specialist nodes may loop back to themselves for
follow-up tool calls before reaching `respond`.

#### 6.5.2 State Schema (LLD)

| Field | Type | Purpose |
|---|---|---|
| messages | `list[BaseMessage]` | Conversation history for the current session |
| intent | enum | schedule / debug / monitor / ambiguous |
| tool_calls_made | `list[str]` | Audit trail of tools invoked this turn |
| retrieved_context | `list[str]` | RAG chunks retrieved for the current query |
| pending_confirmation | bool | Gate for destructive tool execution |

#### 6.5.3 RAG Pipeline (LLD)

- Ingestion: logs chunked by `job_id` + time window; runbook docs chunked via `RecursiveCharacterTextSplitter` (~500 tokens, 50 overlap).
- Embedding: `bge-small` (self-hosted) or `text-embedding-3-small`.
- Store: pgvector, reusing the existing PostgreSQL instance — avoids standing up a separate vector DB.
- Retrieval: top-k=5 similarity search, followed by a cross-encoder reranking pass (`bge-reranker-base`) before the context is passed to the LLM.

#### 6.5.4 Tool-Calling Contract (LLD)

- Each tool is a typed function (Pydantic-validated args/return) wrapping an existing Gateway/Scheduler REST endpoint — the agent never re-implements scheduling logic.
- Tools flagged `destructive=True` (`cancel_job`, `bulk_requeue`) route through the `clarify` node: the agent states the intended action and waits for explicit confirmation before the tool executes.

#### 6.5.5 DSA mapping within the Agentic layer

- Graph — the LangGraph itself is a directed graph (with cycles allowed for follow-up loops, unlike the Scheduler's strict DAG).
- Hashmap — session-state lookup by `session_id` (Redis).
- Priority-ranked retrieval — reranking step is effectively a top-k selection problem over similarity scores.

## 7. DSA Pattern Summary (cross-cutting)

| Pattern | Used In | Why |
|---|---|---|
| Sliding Window | Rate Limiter | Accurate per-client request rate tracking with bounded memory |
| Circular Buffer | Rate Limiter (Gateway edge) | Bounded in-memory timestamp log without unbounded growth |
| Queue | Rate Limiter, Worker Pool | FIFO processing of requests/jobs |
| Min-Heap | Task Scheduler | O(log n) next-job selection by priority/time |
| Graph / DAG + Topological Sort | Task Scheduler | Dependency-safe job ordering, cycle detection |
| Hashmap | API Gateway, Agent session store | O(1) routing and session lookups |
| Consistent Hashing | API Gateway (v2 load balancing) | Minimal remapping when instances scale |
| Graph (cyclic) | Agentic AI Ops Layer (LangGraph) | Multi-step agent reasoning with follow-up loops |

## 8. Development Roadmap — Milestones

See [ROADMAP.md](../ROADMAP.md) for the live, checkbox-tracked version of this
section.

## 9. Technology Stack

| Layer | Choice |
|---|---|
| Service APIs | Python 3.11+, FastAPI |
| Agent Framework | LangChain + LangGraph |
| LLM | OpenAI gpt-4o-mini or Claude API (swappable) |
| Vector Store | PostgreSQL + pgvector |
| Embeddings | bge-small-en (self-hosted) |
| Cache / Queue / Counters | Redis |
| Primary DB | PostgreSQL |
| Observability | Langfuse |
| Deployment | Docker Compose (v1), Kubernetes-ready design |

## 10. Assumptions & Constraints

- Single-region deployment for v1; multi-region is a future enhancement.
- LLM calls assume API access (OpenAI/Anthropic) with acceptable latency; local model fallback (Ollama) is a stretch goal.
- Traffic volumes are assumed to fit within a single Redis instance for v1; Redis Cluster is a scaling path, not a v1 requirement.
- Agentic layer is a control-plane addition — it must never be a single point of failure for core Gateway/Scheduler request handling.
