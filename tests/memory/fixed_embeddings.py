"""Deterministic embeddings for memory tests (no API calls)."""

from __future__ import annotations

import math
from typing import Callable


def vectors_with_cosine_similarity(cosine_sim: float) -> tuple[list[float], list[float]]:
    """Return (document, query) unit vectors whose cosine similarity is ``cosine_sim``."""
    cosine_sim = max(-1.0, min(1.0, cosine_sim))
    doc = [1.0, 0.0, 0.0]
    sine = math.sqrt(max(0.0, 1.0 - cosine_sim * cosine_sim))
    query = [cosine_sim, sine, 0.0]
    return doc, query


class MappedEmbeddings:
    """Embed texts via an explicit map; unmapped texts get a fixed fallback vector."""

    def __init__(
        self,
        vectors: dict[str, list[float]],
        *,
        fallback: Callable[[str], list[float]] | None = None,
    ):
        self._vectors = vectors
        self._fallback = fallback or (lambda _text: [0.0, 0.0, 1.0])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(text, self._fallback(text)) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors.get(text, self._fallback(text))[::]


class CalibrationEmbeddings:
    """
    Fixture-world memory calibration: each fact sits on its own axis; queries
    activate one or more axes so labelled pairs have predictable cosine scores.
    """

    def __init__(self, facts: dict[str, str], queries: dict[str, str | None]):
        self._fact_ids = list(facts.keys())
        self._fact_text = facts
        self._query_labels = queries
        dim = len(self._fact_ids) + 1
        self._shared = 1.0 / math.sqrt(dim)

        self._vectors: dict[str, list[float]] = {}
        for index, fact_id in enumerate(self._fact_ids):
            vec = [0.0] * dim
            vec[index] = 1.0
            vec[-1] = self._shared
            self._normalize(vec)
            self._vectors[facts[fact_id]] = vec

        for query, label in queries.items():
            if label is None:
                vec = [0.0] * (dim - 1)
                vec.append(1.0)
            else:
                idx = self._fact_ids.index(label)
                vec = [0.0] * dim
                vec[idx] = 0.92
                vec[-1] = self._shared
            self._normalize(vec)
            self._vectors[query] = vec

    @staticmethod
    def _normalize(vec: list[float]) -> None:
        norm = math.sqrt(sum(x * x for x in vec))
        if norm:
            for i in range(len(vec)):
                vec[i] /= norm

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors[text][:]
