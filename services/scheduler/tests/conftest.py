import fakeredis
import pytest_asyncio

from app.dispatcher import Scheduler
from app.leader_election import LeaderElection
from tests.fakes import InMemoryJobRepository


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def repository():
    return InMemoryJobRepository()


@pytest_asyncio.fixture
async def scheduler(repository, redis_client):
    leader = LeaderElection(redis_client, "test:leader", ttl_seconds=5.0, instance_id="test-instance")
    return Scheduler(repository, redis_client, leader)
