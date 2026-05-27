from __future__ import annotations

from typing import Sequence

import httpx

from app.core.config import Settings, get_settings


class DashScopeEmbeddingClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        batch_size = max(1, min(self.settings.embedding_batch_size, 10))
        for index in range(0, len(texts), batch_size):
            embeddings.extend(await self._embed_batch(list(texts[index : index + batch_size])))
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_documents([text])
        if not embeddings:
            raise RuntimeError("Embedding service returned no vectors.")
        return embeddings[0]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required for embeddings.")

        url = f"{self.settings.dashscope_base_url.rstrip('/')}/embeddings"
        payload = {
            "model": self.settings.dashscope_embedding_model,
            "input": texts,
            "dimensions": self.settings.embedding_dimensions,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        items = sorted(body.get("data", []), key=lambda item: int(item.get("index", 0)))
        embeddings = [item.get("embedding") for item in items]
        if len(embeddings) != len(texts):
            raise RuntimeError("Embedding service returned an unexpected number of vectors.")
        return [list(map(float, embedding)) for embedding in embeddings]
