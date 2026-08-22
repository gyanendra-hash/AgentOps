from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import create_pool, run_migrations
from app.embeddings import EmbeddingProvider, LocalEmbeddingProvider, OpenAIEmbeddingProvider
from app.graph import build_graph
from app.ingest import ingest_file
from app.llm import AnswerGenerator, AnthropicAnswerGenerator, OpenAIAnswerGenerator
from app.postgres_repository import PostgresEmbeddingRepository
from app.reranker import CrossEncoderReranker

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

    app.state.pool = pool
    app.state.graph = build_graph(
        embedding_provider,
        repository,
        reranker,
        answer_generator,
        top_k=settings.top_k,
        min_score=settings.min_score,
    )

    yield

    await pool.close()


app = FastAPI(title="AgentOps Agent Ops (RAG)", lifespan=lifespan)


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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
