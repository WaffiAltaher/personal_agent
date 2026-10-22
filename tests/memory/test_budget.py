# tests/memory/test_budget.py
import pytest

from agent.memory.budget import ContextBudgetManager
from agent.memory.semantic import MemoryChunk


@pytest.fixture
def mgr():
    return ContextBudgetManager()


def test_estimate_tokens(mgr):
    assert mgr.estimate_tokens("") == 0
    assert mgr.estimate_tokens("a" * 400) == 100
    assert mgr.estimate_tokens("hello world") == 2  # 11 chars // 4


def test_trim_memory_results_respects_budget(mgr):
    chunks = [
        MemoryChunk(content="a" * 400, source="documents", score=0.9),  # 100 tokens
        MemoryChunk(content="b" * 400, source="documents", score=0.8),  # 100 tokens
        MemoryChunk(content="c" * 400, source="documents", score=0.7),  # 100 tokens
    ]

    result = mgr.trim_memory_results(chunks, budget=250)
    assert len(result) == 2
    assert result[0].score == 0.9
    assert result[1].score == 0.8

    result = mgr.trim_memory_results(chunks, budget=50)
    assert result == []

    result = mgr.trim_memory_results(chunks, budget=500)
    assert len(result) == 3
