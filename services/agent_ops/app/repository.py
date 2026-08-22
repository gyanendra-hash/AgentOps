from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float  # cosine similarity, higher = more relevant


class EmbeddingRepository(Protocol):
    """Storage boundary for embedded chunks. `PostgresEmbeddingRepository`
    (pgvector) is the real implementation; tests use an in-memory fake
    (tests/fakes.py) computing cosine similarity in Python, the same
    trade-off the Scheduler makes testing against a fake `JobRepository`
    instead of real Postgres."""

    async def add_chunks(self, chunks: list[tuple[Chunk, list[float]]]) -> None: ...

    async def top_k(self, query_embedding: list[float], k: int) -> list[ScoredChunk]:
        """Highest-cosine-similarity chunks first."""
        ...

    async def count(self) -> int: ...
