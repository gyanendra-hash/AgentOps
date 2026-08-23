from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.db import create_pool, run_migrations
from app.embeddings import EmbeddingProvider, LocalEmbeddingProvider, OpenAIEmbeddingProvider
from app.graph import build_graph
from app.ingest import ingest_file
from app.intent import AnthropicIntentClassifier, IntentClassifier, OpenAIIntentClassifier
from app.llm import AnswerGenerator, AnthropicAnswerGenerator, OpenAIAnswerGenerator
from app.monitor_agent import run_monitor
from app.orchestrator import INITIAL_ORCHESTRATOR_STATE, build_orchestrator_graph
from app.pending_actions import PendingActionStore
from app.postgres_repository import PostgresEmbeddingRepository
from app.rate_limiter_client import RateLimiterClient
from app.reranker import CrossEncoderReranker
from app.scheduler_agent import build_scheduler_agent_graph, execute_confirmed_action
from app.scheduler_client import SchedulerClient
from app.tool_llm import AnthropicToolCallingLLM, OpenAIToolCallingLLM, ToolCallingLLM

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
RUNBOOK_PATH = Path(__file__).resolve().parent.parent / "runbook" / "runbook.md"


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAIEmbeddingProvider(settings.openai_api_key)
    return LocalEmbeddingProvider()


def build_answer_generator(settings: Settings) -> AnswerGenerator:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicAnswerGenerator(
            settings.anthropic_api_key, model=settings.llm_model or "claude-sonnet-5"
        )
    if not settings.openai_api_key:
        raise RuntimeError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
    return OpenAIAnswerGenerator(settings.openai_api_key, model=settings.llm_model or "gpt-4o-mini")


def build_tool_llm(settings: Settings) -> ToolCallingLLM:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicToolCallingLLM(
            settings.anthropic_api_key, model=settings.llm_model or "claude-sonnet-5"
        )
    if not settings.openai_api_key:
        raise RuntimeError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
    return OpenAIToolCallingLLM(settings.openai_api_key, model=settings.llm_model or "gpt-4o-mini")


def build_intent_classifier(settings: Settings) -> IntentClassifier:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicIntentClassifier(
            settings.anthropic_api_key, model=settings.llm_model or "claude-sonnet-5"
        )
    if not settings.openai_api_key:
        raise RuntimeError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
    return OpenAIIntentClassifier(settings.openai_api_key, model=settings.llm_model or "gpt-4o-mini")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = await create_pool(settings.database_url)
    await run_migrations(pool, MIGRATIONS_DIR)

    repository = PostgresEmbeddingRepository(pool)
    embedding_provider = build_embedding_provider(settings)
    reranker = CrossEncoderReranker()
    answer_generator = build_answer_generator(settings)

    if RUNBOOK_PATH.exists() and await repository.count() == 0:
        await ingest_file(
            RUNBOOK_PATH,
            "runbook",
            embedding_provider,
            repository,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    http_client = httpx.AsyncClient(timeout=5.0)
    scheduler_client = SchedulerClient(http_client, settings.scheduler_url)
    rate_limiter_client = RateLimiterClient(http_client, settings.rate_limiter_url)
    pending_actions = PendingActionStore(redis, settings.confirmation_ttl_seconds)
    tool_llm = build_tool_llm(settings)
    intent_classifier = build_intent_classifier(settings)

    debug_graph = build_graph(
        embedding_provider,
        repository,
        reranker,
        answer_generator,
        top_k=settings.top_k,
        min_score=settings.min_score,
    )
    scheduler_agent_graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)

    app.state.pool = pool
    app.state.redis = redis
    app.state.http_client = http_client
    app.state.scheduler_client = scheduler_client
    app.state.rate_limiter_client = rate_limiter_client
    app.state.pending_actions = pending_actions
    app.state.graph = debug_graph
    app.state.scheduler_agent_graph = scheduler_agent_graph
    app.state.orchestrator_graph = build_orchestrator_graph(
        intent_classifier,
        scheduler_agent_graph,
        debug_graph,
        scheduler_client,
        rate_limiter_client,
        pending_actions,
    )

    yield

    await http_client.aclose()
    await redis.aclose()
    await pool.close()


app = FastAPI(title="AgentOps Agent Ops (RAG + Tool-Calling)", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[str]


@app.post("/v1/debug/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request) -> AskResponse:
    graph = request.app.state.graph
    result = await graph.ainvoke(
        {"question": payload.question, "retrieved_context": [], "sources": [], "answer": ""}
    )
    return AskResponse(answer=result["answer"], sources=result["sources"])


class AgentAskRequest(BaseModel):
    question: str


class AgentAskResponse(BaseModel):
    response: str
    needs_confirmation: bool = False
    confirmation_token: str | None = None
    result: Any = None


class AgentConfirmRequest(BaseModel):
    confirmation_token: str
    confirmed: bool = True


_SCHEDULER_AGENT_INITIAL_STATE = {
    "tool_name": None,
    "tool_args": {},
    "rationale": "",
    "needs_confirmation": False,
    "confirmation_token": None,
    "result": None,
    "error": None,
    "response": "",
}


@app.post("/v1/agent/schedule", response_model=AgentAskResponse)
async def agent_schedule(payload: AgentAskRequest, request: Request) -> AgentAskResponse:
    graph = request.app.state.scheduler_agent_graph
    result = await graph.ainvoke({"question": payload.question, **_SCHEDULER_AGENT_INITIAL_STATE})
    return AgentAskResponse(
        response=result["response"],
        needs_confirmation=result["needs_confirmation"],
        confirmation_token=result["confirmation_token"],
        result=result.get("result"),
    )


@app.post("/v1/agent/confirm", response_model=AgentAskResponse)
async def agent_confirm(payload: AgentConfirmRequest, request: Request) -> AgentAskResponse:
    pending_actions: PendingActionStore = request.app.state.pending_actions
    if not payload.confirmed:
        await pending_actions.delete(payload.confirmation_token)
        return AgentAskResponse(response="Cancelled -- no action taken.")

    scheduler_client: SchedulerClient = request.app.state.scheduler_client
    response_text, result, _error = await execute_confirmed_action(
        scheduler_client, pending_actions, payload.confirmation_token
    )
    return AgentAskResponse(response=response_text, result=result)


@app.post("/v1/agent/ask", response_model=AgentAskResponse)
async def agent_ask(payload: AgentAskRequest, request: Request) -> AgentAskResponse:
    """ROADMAP 5.1/5.2: the unified entry point -- classifies intent and
    routes to the Scheduler Agent, the debug/RAG graph, or the Monitor
    Agent. /v1/debug/ask and /v1/agent/schedule remain available for direct
    access when the caller already knows which specialist it wants."""
    graph = request.app.state.orchestrator_graph
    result = await graph.ainvoke({"question": payload.question, **INITIAL_ORCHESTRATOR_STATE})
    return AgentAskResponse(
        response=result["response"],
        needs_confirmation=result["needs_confirmation"],
        confirmation_token=result["confirmation_token"],
        result=result.get("result"),
    )


class MonitorStatusResponse(BaseModel):
    response: str
    queue_depth: dict | None = None
    rate_limit: dict | None = None


@app.get("/v1/monitor/status", response_model=MonitorStatusResponse)
async def monitor_status(
    request: Request, client_id: str | None = None, tier: str = "default"
) -> MonitorStatusResponse:
    """Direct, deterministic access to the Monitor Agent (ROADMAP 5.3) --
    no LLM call, always available."""
    scheduler_client: SchedulerClient = request.app.state.scheduler_client
    rate_limiter_client: RateLimiterClient = request.app.state.rate_limiter_client
    response_text, data = await run_monitor(
        scheduler_client, rate_limiter_client, client_id=client_id, tier=tier
    )
    return MonitorStatusResponse(
        response=response_text,
        queue_depth=data.get("queue_depth"),
        rate_limit=data.get("rate_limit"),
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
