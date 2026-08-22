"""Ingestion pipeline (ROADMAP 3.3): chunk a runbook/log file, embed each
chunk, store it."""

from pathlib import Path

from app.chunking import chunk_text
from app.embeddings import EmbeddingProvider
from app.repository import Chunk, EmbeddingRepository


async def ingest_file(
    path: Path,
    source: str,
    embedding_provider: EmbeddingProvider,
    repository: EmbeddingRepository,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> int:
    return await ingest_text(
        path.read_text(encoding="utf-8"),
        source,
        embedding_provider,
        repository,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


async def ingest_text(
    text: str,
    source: str,
    embedding_provider: EmbeddingProvider,
    repository: EmbeddingRepository,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> int:
    chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        return 0

    embeddings = await embedding_provider.embed(chunks)
    records = [
        (Chunk(id="", text=chunk, source=source, metadata={"chunk_index": i}), embedding)
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    await repository.add_chunks(records)
    return len(records)
