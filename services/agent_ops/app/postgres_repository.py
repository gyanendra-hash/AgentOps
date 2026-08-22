from __future__ import annotations

import asyncpg

from app.repository import Chunk, ScoredChunk

_TOP_K_QUERY = """
    SELECT id, source, chunk_text, metadata, 1 - (embedding <=> $1) AS score
    FROM embeddings
    ORDER BY embedding <=> $1
    LIMIT $2
"""


class PostgresEmbeddingRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add_chunks(self, chunks: list[tuple[Chunk, list[float]]]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for chunk, embedding in chunks:
                    await conn.execute(
                        """
                        INSERT INTO embeddings (source, chunk_text, metadata, embedding)
                        VALUES ($1, $2, $3::jsonb, $4)
                        """,
                        chunk.source,
                        chunk.text,
                        chunk.metadata,
                        embedding,
                    )

    async def top_k(self, query_embedding: list[float], k: int) -> list[ScoredChunk]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_TOP_K_QUERY, query_embedding, k)
        return [
            ScoredChunk(
                chunk=Chunk(
                    id=str(row["id"]),
                    text=row["chunk_text"],
                    source=row["source"],
                    metadata=row["metadata"],
                ),
                score=float(row["score"]),
            )
            for row in rows
        ]

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT count(*) FROM embeddings")
