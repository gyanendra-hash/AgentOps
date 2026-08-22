import pytest_asyncio

from tests.fakes import FakeAnswerGenerator, FakeEmbeddingProvider, FakeReranker, InMemoryEmbeddingRepository


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
