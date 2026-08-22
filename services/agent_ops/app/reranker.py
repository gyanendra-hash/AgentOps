"""Cross-encoder reranking (ROADMAP 3.7). A bi-encoder similarity search
(top_k retrieval) is fast but approximate; a cross-encoder scores each
(query, chunk) pair jointly and is far more accurate at judging relevance --
it's just too slow to run over the whole corpus, so it only re-scores the
top_k candidates retrieval already narrowed down to."""

import asyncio
from typing import Protocol

from app.repository import ScoredChunk


class Reranker(Protocol):
    async def rerank(self, query: str, candidates: list[ScoredChunk]) -> list[ScoredChunk]: ...


class CrossEncoderReranker:
    """bge-reranker-base via sentence-transformers -- self-hosted, no API key."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)

    async def rerank(self, query: str, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        if not candidates:
            return []

        def _score() -> list[float]:
            pairs = [(query, c.chunk.text) for c in candidates]
            return list(self._model.predict(pairs))

        scores = await asyncio.to_thread(_score)
        rescored = [
            ScoredChunk(chunk=c.chunk, score=float(s)) for c, s in zip(candidates, scores)
        ]
        return sorted(rescored, key=lambda c: c.score, reverse=True)
