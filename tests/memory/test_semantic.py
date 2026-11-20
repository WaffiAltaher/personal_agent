# tests/memory/test_semantic.py
"""
Semantic memory tests use a fake deterministic embeddings class so no
Google API key is required and tests are fast and hermetic.
"""
import pytest
from unittest.mock import patch

from agent.config import settings
from agent.memory.semantic import MemoryChunk, SemanticMemory


class _FakeEmbeddings:
    """
    Constant unit embeddings: every text maps to the same 16-d unit vector.
    With cosine space every query/document pair scores 1.0, which is enough
    to test ingestion, retrieval, and threshold logic without a real model.
    """

    _VEC: list[float] = [1.0] + [0.0] * 15  # 16-dimensional unit vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._VEC for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._VEC


@pytest.fixture
def mem(tmp_path):
    with patch(
        "agent.memory.semantic.create_embeddings",
        return_value=_FakeEmbeddings(),
    ):
        semantic = SemanticMemory(persist_dir=str(tmp_path / "chroma"))
    yield semantic
    semantic.close()


def test_ingest_and_search_documents(mem, monkeypatch):
    doc_id = mem.ingest_document(
        text="LangGraph is a library for building stateful multi-actor applications.",
        metadata={"source": "docs", "title": "LangGraph intro"},
    )
    assert isinstance(doc_id, str) and len(doc_id) > 0

    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    results = mem.search_documents("LangGraph stateful applications", k=5)
    assert len(results) >= 1
    assert all(isinstance(c, MemoryChunk) for c in results)
    assert results[0].source == "documents"
    assert "LangGraph" in results[0].content


def test_remember_and_search_memories(mem, monkeypatch):
    memory_id = mem.remember("LangChain is a framework for building LLM applications.")

    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    results = mem.search_memories("LangChain framework", k=3)
    assert len(results) >= 1
    assert results[0].source == "memories"
    assert "LangChain" in results[0].content
    assert results[0].metadata["memory_id"] == memory_id


def test_score_threshold_filtering(mem, monkeypatch):
    mem.ingest_document(
        text="The quick brown fox jumps over the lazy dog.",
        metadata={"source": "test"},
    )

    monkeypatch.setattr(settings, "memory_score_threshold", 1.1)
    assert mem.search_documents("fox", k=5) == []

    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    assert len(mem.search_documents("fox", k=5)) >= 1
