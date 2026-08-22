"""Standalone top-k retrieval (ROADMAP 3.4)."""

from app.embeddings import EmbeddingProvider
from app.repository import EmbeddingRepository, ScoredChunk


async def retrieve(
    question: str,
    embedding_provider: EmbeddingProvider,
    repository: EmbeddingRepository,
    *,
    k: int = 5,
    min_score: float = 0.0,
) -> list[ScoredChunk]:
    """Embed the question, pull the top-k nearest chunks, and drop anything
    below `min_score` (ROADMAP 3.8: irrelevant-chunk filtering) so a
    dissimilar corpus doesn't get force-fed to the LLM as if it were
    relevant context."""
    query_embedding = await embedding_provider.embed_one(question)
    candidates = await repository.top_k(query_embedding, k)
    return [c for c in candidates if c.score >= min_score]
