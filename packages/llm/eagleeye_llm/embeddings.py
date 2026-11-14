"""Embedder port + LiteLLM adapter (EMBED_MODEL is pure config)."""

from typing import Any, Protocol

import litellm

EMBED_BATCH_SIZE = 64


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _vector_of(item: Any) -> list[float]:
    raw = item["embedding"] if isinstance(item, dict) else item.embedding
    return [float(x) for x in raw]


class LiteLLMEmbedder:
    def __init__(self, model: str, dim: int) -> None:
        self._model = model
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start : start + EMBED_BATCH_SIZE]
            resp = await litellm.aembedding(model=self._model, input=batch, timeout=30.0)
            items = sorted(
                resp.data,
                key=lambda d: d["index"] if isinstance(d, dict) else getattr(d, "index", 0),
            )
            batch_vectors = [_vector_of(item) for item in items]
            if len(batch_vectors) != len(batch):
                raise ValueError(f"embedding count mismatch: {len(batch_vectors)} != {len(batch)}")
            for vec in batch_vectors:
                if len(vec) != self._dim:
                    raise ValueError(
                        f"embedding dim {len(vec)} != EMBED_DIM {self._dim} "
                        f"(model {self._model}); fix EMBED_DIM and the vector(D) column"
                    )
            vectors.extend(batch_vectors)
        return vectors


class CachingEmbedder:
    """Query embeddings through EagleEye's cache: identical text and model → same vector.
    Used for searches only (ingestion embeds new text and gains nothing from it)."""

    def __init__(self, inner: Embedder, cache: Any, model: str) -> None:
        self._inner = inner
        self._cache = cache
        self._model = model

    @property
    def dim(self) -> int:
        return self._inner.dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        found: dict[int, list[float]] = {}
        for i, text in enumerate(texts):
            hit = await self._cache.get("embedding", (self._model, self.dim, text))
            if hit is not None and len(hit.get("v", [])) == self.dim:
                found[i] = [float(x) for x in hit["v"]]
        missing = [i for i in range(len(texts)) if i not in found]
        if missing:
            fresh = await self._inner.embed([texts[i] for i in missing])
            for i, vec in zip(missing, fresh, strict=True):
                found[i] = vec
                await self._cache.put("embedding", (self._model, self.dim, texts[i]), {"v": vec})
        return [found[i] for i in range(len(texts))]
