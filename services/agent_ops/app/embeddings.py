"""Embedding providers (ROADMAP 3.1/3.3), per SRS 6.5.3: "bge-small (self-hosted)
or text-embedding-3-small". Both are implemented; `LocalEmbeddingProvider` is
the default so a fresh checkout needs no API key to ingest and query the
runbook. Heavy imports (sentence-transformers, openai) are deferred into
__init__ so importing this module -- and therefore app.main, for tests that
never instantiate these classes -- doesn't require either package installed."""

import asyncio
from typing import Protocol


class EmbeddingProvider(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_one(self, text: str) -> list[float]: ...


class LocalEmbeddingProvider:
    """bge-small-en-v1.5 via sentence-transformers -- self-hosted, no API key."""

    dim = 384

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            return self._model.encode(texts, normalize_embeddings=True).tolist()

        return await asyncio.to_thread(_encode)

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class OpenAIEmbeddingProvider:
    """text-embedding-3-small via the OpenAI API -- needs OPENAI_API_KEY."""

    dim = 1536

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
