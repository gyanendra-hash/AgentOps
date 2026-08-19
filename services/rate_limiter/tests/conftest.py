import fakeredis
import pytest_asyncio


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()
