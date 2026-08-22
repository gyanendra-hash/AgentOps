from pathlib import Path

from app.ingest import ingest_file, ingest_text
from app.retrieval import retrieve

RUNBOOK_PATH = Path(__file__).resolve().parent.parent / "runbook" / "runbook.md"


async def test_ingest_text_stores_chunks(embedding_provider, repository):
    count = await ingest_text(
        "## Scenario: X\n\nSome details about X that are long enough to form a chunk.",
        "runbook",
        embedding_provider,
        repository,
        chunk_size=500,
        chunk_overlap=50,
    )
    assert count > 0
    assert await repository.count() == count


async def test_ingest_empty_text_stores_nothing(embedding_provider, repository):
    count = await ingest_text("   ", "runbook", embedding_provider, repository)
    assert count == 0
    assert await repository.count() == 0


async def test_ingest_real_runbook_file(embedding_provider, repository):
    count = await ingest_file(
        RUNBOOK_PATH, "runbook", embedding_provider, repository, chunk_size=500, chunk_overlap=50
    )
    assert count >= 10  # at least one chunk per scenario
    assert await repository.count() == count


async def test_retrieval_finds_relevant_chunk_after_ingestion(embedding_provider, repository):
    await ingest_file(RUNBOOK_PATH, "runbook", embedding_provider, repository)

    results = await retrieve(
        "the dead letter queue keeps growing", embedding_provider, repository, k=3
    )

    assert any("dead-letter" in r.chunk.text.lower() or "dead letter" in r.chunk.text.lower() for r in results)
