import fakeredis
import httpx
import pytest_asyncio

from app.pending_actions import PendingActionStore
from app.scheduler_client import SchedulerClient
from tests.fakes import (
    FakeAnswerGenerator,
    FakeEmbeddingProvider,
    FakeReranker,
    FakeToolCallingLLM,
    InMemoryEmbeddingRepository,
)

SCHEDULER_BASE_URL = "http://scheduler.test"


@pytest_asyncio.fixture
async def embedding_provider():
    return FakeEmbeddingProvider()


@pytest_asyncio.fixture
async def repository():
    return InMemoryEmbeddingRepository()


@pytest_asyncio.fixture
async def reranker():
    return FakeReranker()


@pytest_asyncio.fixture
async def answer_generator():
    return FakeAnswerGenerator()


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def scheduler_client():
    async with httpx.AsyncClient() as http_client:
        yield SchedulerClient(http_client, SCHEDULER_BASE_URL)


@pytest_asyncio.fixture
async def pending_actions(redis_client):
    return PendingActionStore(redis_client, ttl_seconds=300)


@pytest_asyncio.fixture
async def tool_llm():
    return FakeToolCallingLLM()
