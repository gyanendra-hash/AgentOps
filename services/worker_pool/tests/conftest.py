import fakeredis
import pytest_asyncio

from app.worker import Worker
from tests.fakes import FakeSchedulerClient


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def scheduler_client():
    return FakeSchedulerClient()


@pytest_asyncio.fixture
async def worker(redis_client, scheduler_client):
    return Worker(
        redis_client,
        scheduler_client,
        max_retries=3,
        base_backoff_seconds=0.01,
        poll_timeout_seconds=0.1,
    )
