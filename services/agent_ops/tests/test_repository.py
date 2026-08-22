from app.repository import Chunk


async def test_top_k_ranks_by_similarity(embedding_provider, repository):
    chunks = [
        Chunk(id="", text="gateway returns 503 for every request", source="runbook"),
        Chunk(id="", text="rate limiter token bucket capacity refill", source="runbook"),
        Chunk(id="", text="dead letter queue growing jobs failing", source="runbook"),
    ]
    embeddings = await embedding_provider.embed([c.text for c in chunks])
    await repository.add_chunks(list(zip(chunks, embeddings)))

    query_embedding = await embedding_provider.embed_one("why is the gateway returning 503")
    results = await repository.top_k(query_embedding, k=2)

    assert len(results) == 2
    assert "503" in results[0].chunk.text
    assert results[0].score >= results[1].score


async def test_top_k_respects_k(embedding_provider, repository):
    chunks = [Chunk(id="", text=f"chunk number {i}", source="runbook") for i in range(5)]
    embeddings = await embedding_provider.embed([c.text for c in chunks])
    await repository.add_chunks(list(zip(chunks, embeddings)))

    query_embedding = await embedding_provider.embed_one("chunk number 3")
    results = await repository.top_k(query_embedding, k=3)

    assert len(results) == 3


async def test_count_reflects_stored_chunks(embedding_provider, repository):
    assert await repository.count() == 0
    chunks = [Chunk(id="", text="a", source="runbook"), Chunk(id="", text="b", source="runbook")]
    embeddings = await embedding_provider.embed([c.text for c in chunks])
    await repository.add_chunks(list(zip(chunks, embeddings)))
    assert await repository.count() == 2
