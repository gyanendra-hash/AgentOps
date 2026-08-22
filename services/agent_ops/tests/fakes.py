"""Test doubles standing in for the real (heavy, API-key-requiring)
providers: a hashed bag-of-words embedding instead of bge-small-en, an
in-memory cosine-similarity store instead of pgvector, a pass-through
reranker, and a templated answer generator instead of a real LLM call. This
mirrors the fakeredis/InMemoryJobRepository trade-off elsewhere in the repo
-- the FakeEmbeddingProvider is deterministic and word-overlap-sensitive
(not random), so retrieval-ranking tests are actually meaningful."""

import hashlib
import math

from app.repository import Chunk, ScoredChunk


# Boilerplate that appears in nearly every runbook chunk ("Scenario",
# "Symptoms:", "what", "should"...) -- left in, it dilutes the bag-of-words
# signal enough that unrelated chunks can out-rank the actually-relevant one
# purely on shared structure words. A real embedding model handles this via
# learned attention; the fake needs an explicit stopword filter instead.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "being", "been",
    "to", "of", "in", "on", "for", "and", "or", "but", "if", "so", "at",
    "it", "its", "this", "that", "what", "why", "how", "should", "i",
    "we", "you", "do", "does", "did", "not", "no", "very", "every",
    "single", "look", "check", "wrong", "happened", "expected", "tune",
    "scenario", "symptoms", "likely", "causes", "fix", "when",
}


class FakeEmbeddingProvider:
    # A larger hash space than a real toy example needs, specifically to
    # avoid spurious bucket collisions between unrelated words -- collisions
    # were producing false-positive "similar" chunks in retrieval tests.
    dim = 4096

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in text.lower().split():
            word = word.strip(".,`:;!?()")
            if not word or word in _STOPWORDS:
                continue
            idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


class InMemoryEmbeddingRepository:
    def __init__(self) -> None:
        self._rows: list[tuple[Chunk, list[float]]] = []

    async def add_chunks(self, chunks: list[tuple[Chunk, list[float]]]) -> None:
        for chunk, embedding in chunks:
            stored = Chunk(
                id=chunk.id or f"chunk-{len(self._rows)}",
                text=chunk.text,
                source=chunk.source,
                metadata=chunk.metadata,
            )
            self._rows.append((stored, embedding))

    async def top_k(self, query_embedding: list[float], k: int) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk=chunk, score=_cosine(query_embedding, embedding))
            for chunk, embedding in self._rows
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:k]

    async def count(self) -> int:
        return len(self._rows)


class FakeReranker:
    """Pass-through -- keeps retrieval's own similarity ordering."""

    async def rerank(self, query: str, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        return candidates


class FakeAnswerGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def generate(self, question: str, context_chunks: list[str]) -> str:
        self.calls.append((question, context_chunks))
        if not context_chunks:
            return "I don't have enough information to answer that."
        return f"Based on the runbook: {context_chunks[0]}"
