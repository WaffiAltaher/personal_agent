"""Memory retrieval tools: agent-written queries, no hidden rewrite."""

import importlib.util
from unittest.mock import patch

import pytest

from agent.memory.episodic import EpisodicMemory, RunRecord
from agent.memory.semantic import SemanticMemory


class FixedEmbeddings:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


@pytest.fixture
def episodic(tmp_path):
    db = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))
    yield db
    db.close()


@pytest.fixture
def semantic(tmp_path):
    with patch("agent.memory.semantic.GoogleGenerativeAIEmbeddings", return_value=FixedEmbeddings()):
        yield SemanticMemory(persist_dir=str(tmp_path / "chroma"))


@pytest.fixture
def tool_memory(monkeypatch, episodic, semantic):
    import agent.memory

    monkeypatch.setattr(agent.memory, "_episodic", episodic)
    monkeypatch.setattr(agent.memory, "_semantic", semantic)
    return episodic, semantic


def test_recall_module_is_removed():
    assert importlib.util.find_spec("agent.memory.recall") is None


def test_retrieve_episodic_memory_reports_no_matches_plainly(tool_memory):
    from agent.tools.memory import retrieve_episodic_memory

    result = retrieve_episodic_memory.invoke({"terms": "VAT", "since": "2026-10-01"})

    assert result == "No matching runs found in episodic memory."


def test_retrieve_episodic_memory_searches_agent_terms_and_dates(tool_memory):
    from agent.tools.memory import retrieve_episodic_memory

    episodic, _ = tool_memory
    episodic.log_run(
        RunRecord(
            user_input="How much VAT for Q3 2026?",
            final_output="You asked about VAT.",
            timestamp="2026-10-02T09:00:00+00:00",
        )
    )
    episodic.log_run(
        RunRecord(
            user_input="Weather today",
            final_output="Sunny",
            timestamp="2026-10-02T10:00:00+00:00",
        )
    )

    result = retrieve_episodic_memory.invoke(
        {"terms": "VAT", "since": "2026-10-01", "until": "2026-10-03"}
    )

    assert "How much VAT for Q3 2026?" in result
    assert "Weather today" not in result


def test_retrieve_memory_uses_the_query_directly(tool_memory):
    from agent.tools.memory import retrieve_memory

    _, semantic = tool_memory
    semantic.remember("Quarterly VAT filing deadline is the 28th.")
    queries: list[str] = []
    original = semantic.search_all

    def tracking(query, k=5):
        queries.append(query)
        return original(query, k=k)

    semantic.search_all = tracking  # type: ignore[method-assign]
    retrieve_memory.invoke({"query": "VAT filing deadline"})

    assert queries == ["VAT filing deadline"]
