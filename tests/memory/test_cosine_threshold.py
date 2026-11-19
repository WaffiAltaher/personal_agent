"""Ticket 24: cosine similarity scores and calibrated memory threshold."""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from agent.config import settings
from agent.memory.semantic import SemanticMemory
from memory.calibration_data import CALIBRATION_FACTS, CALIBRATION_QUERIES
from memory.fixed_embeddings import CalibrationEmbeddings, MappedEmbeddings, vectors_with_cosine_similarity


def test_search_score_equals_cosine_similarity(tmp_path, monkeypatch):
    target = 0.73
    doc_vec, query_vec = vectors_with_cosine_similarity(target)
    doc_text = "calibration-doc"
    query_text = "calibration-query"
    embeddings = MappedEmbeddings({doc_text: doc_vec, query_text: query_vec})
    with patch(
        "agent.memory.semantic.create_embeddings",
        return_value=embeddings,
    ):
        mem = SemanticMemory(persist_dir=str(tmp_path / "chroma"))
        mem.remember(doc_text)

    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    hits = mem.search_memories(query_text, k=1)

    assert len(hits) == 1
    assert hits[0].score == pytest.approx(target, abs=1e-3)


def test_calibration_queries_match_labels_at_configured_threshold(tmp_path, monkeypatch):
    embeddings = CalibrationEmbeddings(CALIBRATION_FACTS, CALIBRATION_QUERIES)
    with patch(
        "agent.memory.semantic.create_embeddings",
        return_value=embeddings,
    ):
        mem = SemanticMemory(persist_dir=str(tmp_path / "chroma"))
    for text in CALIBRATION_FACTS.values():
        mem.remember(text)

    threshold = settings.memory_score_threshold
    for query, expected_fact in CALIBRATION_QUERIES.items():
        hits = mem.search_memories(query, k=3)
        if expected_fact is None:
            assert hits == [], f"query should find nothing: {query!r}"
        else:
            assert hits, f"query should match: {query!r}"
            expected_text = CALIBRATION_FACTS[expected_fact]
            assert hits[0].content == expected_text
            assert hits[0].score >= threshold


def test_memory_threshold_lives_only_in_settings():
    sig_docs = inspect.signature(SemanticMemory.search_documents)
    sig_mem = inspect.signature(SemanticMemory.search_memories)
    assert "score_threshold" not in sig_docs.parameters
    assert "score_threshold" not in sig_mem.parameters


def test_l2_store_is_reindexed_to_cosine_on_open(tmp_path, monkeypatch):
    from langchain_chroma import Chroma

    class LegacyEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

    legacy_path = tmp_path / "legacy"
    l2 = Chroma(
        collection_name="memories",
        embedding_function=LegacyEmbeddings(),
        persist_directory=str(legacy_path),
    )
    l2.add_texts(
        ["VAT is 21% in NL"],
        ids=["m1"],
        metadatas=[{"memory_id": "m1"}],
    )
    assert l2._collection.configuration["hnsw"]["space"] == "l2"

    with patch(
        "agent.memory.semantic.create_embeddings",
        return_value=LegacyEmbeddings(),
    ):
        reopened = SemanticMemory(persist_dir=str(legacy_path))

    assert reopened._memories._collection.configuration["hnsw"]["space"] == "cosine"
    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    hits = reopened.search_memories("VAT Netherlands", k=1)
    assert hits and "21%" in hits[0].content
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)
