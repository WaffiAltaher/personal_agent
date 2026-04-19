# tests/memory/test_budget.py
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

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

    # Budget of 250 tokens fits two chunks (100 + 100 = 200 ≤ 250; adding third = 300 > 250)
    result = mgr.trim_memory_results(chunks, budget=250)
    assert len(result) == 2
    # Highest score first
    assert result[0].score == 0.9
    assert result[1].score == 0.8

    # Budget of 50 tokens — nothing fits
    result = mgr.trim_memory_results(chunks, budget=50)
    assert result == []

    # Budget of 500 tokens — all fit
    result = mgr.trim_memory_results(chunks, budget=500)
    assert len(result) == 3


def test_trim_messages_keeps_system_and_recent(mgr):
    system = SystemMessage(content="You are a helpful assistant.")  # ~7 tokens
    msgs = [
        HumanMessage(content="a" * 400),   # 100 tokens
        AIMessage(content="b" * 400),       # 100 tokens
        HumanMessage(content="c" * 400),    # 100 tokens
        AIMessage(content="d" * 400),       # 100 tokens
    ]
    all_messages = [system] + msgs

    # Budget of 220 tokens: system (~7) + 2 most recent messages (100+100=200) = ~207 ≤ 220
    result = mgr.trim_messages(all_messages, budget=220)
    assert result[0] is system  # system message always first
    assert len(result) >= 2      # system + at least one recent message

    # System message is always present even with tiny budget
    result = mgr.trim_messages(all_messages, budget=1)
    assert len(result) == 1
    assert result[0] is system

    # Empty list
    assert mgr.trim_messages([], budget=1000) == []
