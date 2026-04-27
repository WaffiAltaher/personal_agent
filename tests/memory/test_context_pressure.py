# tests/memory/test_context_pressure.py
"""
Context-pressure tests for Phase 3.4.

Validates:
  - TokenCounter counts and classifies messages correctly
  - Budget reports format correctly
  - ContextBudgetManager trims messages and memory chunks within budget
  - check_context_budget node removes messages from state when hard limit exceeded
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages

from agent.memory.budget import ContextBudgetManager, TokenCounter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_conversation() -> list:
    """Load long_conversation.json and convert to LangChain message objects."""
    with open(FIXTURES / "long_conversation.json", encoding="utf-8") as f:
        data = json.load(f)
    messages = []
    for item in data:
        if item["role"] == "human":
            messages.append(HumanMessage(content=item["content"]))
        else:
            messages.append(AIMessage(content=item["content"]))
    return messages


def _load_memory_chunks():
    """Load large_memory_injection.json as MemoryChunk-like objects."""
    from agent.memory.semantic import MemoryChunk

    with open(FIXTURES / "large_memory_injection.json", encoding="utf-8") as f:
        data = json.load(f)
    return [
        MemoryChunk(
            content=item["content"],
            source=item["source"],
            score=item["score"],
            metadata=item.get("metadata", {}),
        )
        for item in data
    ]


def _load_bloated_tool_result() -> str:
    """Load bloated_tool_result.json as a single JSON string (as a tool would return)."""
    with open(FIXTURES / "bloated_tool_result.json", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_baseline_token_count():
    """Empty/minimal state should be well under all budget limits."""
    counter = TokenCounter()
    cbm = ContextBudgetManager()

    messages = [HumanMessage(content="What's in my notes.txt?")]
    counts = counter.count_messages(messages)

    print("\n" + counter.build_budget_report(messages, []))

    assert counts["total"] < 5_000, f"Expected < 5k tokens, got {counts['total']}"
    assert counts["system"] < cbm.SYSTEM_PROMPT_BUDGET
    assert counts["conversation"] < cbm.CONVERSATION_BUDGET
    assert counts["tool_results"] < cbm.TOOL_RESULTS_BUDGET
    assert counts["message_count"] == 1


def test_conversation_bloat():
    """30 back-and-forth pairs should stress the conversation bucket."""
    counter = TokenCounter()
    cbm = ContextBudgetManager()

    messages = _load_conversation()
    counts = counter.count_messages(messages)

    assert counts["conversation"] > 30_000, (
        f"Expected > 30k conversation tokens, got {counts['conversation']}"
    )
    assert counts["message_count"] == 60

    # trim_messages should return fewer messages within budget
    trimmed = cbm.trim_messages(messages, budget=20_000)
    assert len(trimmed) < len(messages), "Trimmed list should be shorter"

    # System messages are always preserved (none here, so check structure)
    trimmed_counts = counter.count_messages(trimmed)
    assert trimmed_counts["total"] <= 20_000, (
        f"Trimmed total {trimmed_counts['total']} exceeds budget 20,000"
    )


def test_tool_result_bloat():
    """25 emails as a ToolMessage should stress the tool_results bucket."""
    counter = TokenCounter()

    raw = _load_bloated_tool_result()
    tool_msg = ToolMessage(content=raw, tool_call_id="fake_call_id")
    messages = [
        HumanMessage(content="Search my email for anything from the legal team."),
        AIMessage(content="I'll search your email now."),
        tool_msg,
    ]
    counts = counter.count_messages(messages)

    assert counts["tool_results"] > 15_000, (
        f"Expected > 15k tool_results tokens, got {counts['tool_results']}"
    )
    assert counts["message_count"] == 3


def test_memory_budget_enforcement():
    """Trim memory chunks down to a hard token budget, highest scores first."""
    counter = TokenCounter()
    cbm = ContextBudgetManager()

    chunks = _load_memory_chunks()
    total_tokens = counter.count_memory_chunks(chunks)

    assert total_tokens > 8_000, f"Expected > 8k memory tokens, got {total_tokens}"

    budget = 3_000
    trimmed = cbm.trim_memory_results(chunks, budget=budget)

    # Total tokens of trimmed set must fit in budget
    trimmed_tokens = counter.count_memory_chunks(trimmed)
    assert trimmed_tokens <= budget, (
        f"Trimmed memory tokens {trimmed_tokens} exceed budget {budget}"
    )

    # Must be sorted by score descending
    for i in range(len(trimmed) - 1):
        assert trimmed[i].score >= trimmed[i + 1].score, (
            "Memory chunks are not sorted by score descending"
        )

    # All chunks above the default threshold should have reasonable scores
    # (fixture scores range from 0.95 to 0.61; budget enforcement picks highest first)
    if trimmed:
        assert trimmed[0].score >= 0.7, (
            "Highest-scored chunk should be above the default threshold"
        )


def test_budget_report_format():
    """build_budget_report output must contain all required sections and correct maths."""
    counter = TokenCounter()
    cbm = ContextBudgetManager()

    messages = [
        SystemMessage(content="You are a helpful agent."),
        HumanMessage(content="What meetings do I have today?"),
        AIMessage(content="Let me check your calendar."),
        ToolMessage(content='[{"title": "Standup", "time": "09:00"}]', tool_call_id="c1"),
        AIMessage(content="You have a standup at 09:00."),
    ]

    chunks = _load_memory_chunks()[:3]
    report = counter.build_budget_report(messages, chunks)

    print("\n" + report)

    # Required section headers
    assert "System prompt:" in report
    assert "Conversation:" in report
    assert "Tool results:" in report
    assert "Memory injection:" in report
    assert "Total:" in report
    assert "Headroom:" in report

    # Headroom percentage is mathematically correct
    counts = counter.count_messages(messages)
    memory_tokens = counter.count_memory_chunks(chunks)
    total = counts["total"] + memory_tokens
    headroom = cbm.MAX_CONTEXT_TOKENS - total
    expected_pct = headroom / cbm.MAX_CONTEXT_TOKENS * 100

    # Extract percentage from report
    for line in report.splitlines():
        if "Headroom:" in line and "%" in line:
            pct_str = line.split("(")[1].rstrip("%)").strip()
            actual_pct = float(pct_str)
            assert abs(actual_pct - expected_pct) < 1.0, (
                f"Headroom % in report ({actual_pct}) differs from expected ({expected_pct:.1f})"
            )
            break


def test_hard_limit_triggers_trim():
    """check_context_budget should emit RemoveMessages when hard limit is exceeded."""
    from agent.graph import check_context_budget

    messages = _load_conversation()
    # Assign IDs so RemoveMessage can reference them (LangGraph normally does this)
    for i, msg in enumerate(messages):
        if not getattr(msg, "id", None):
            object.__setattr__(msg, "id", f"msg_{i:04d}")

    state = {"messages": messages, "token_usage_estimate": None}

    with patch("agent.graph.settings") as mock_settings:
        mock_settings.context_hard_limit = 1_000   # very low — fixture will exceed it
        mock_settings.context_warning_threshold = 500
        update = check_context_budget(state)

    # token_usage_estimate must be populated
    assert update.get("token_usage_estimate") is not None
    assert update["token_usage_estimate"]["total"] > 0

    # When over hard limit, update should contain RemoveMessage objects
    assert "messages" in update, "Expected 'messages' key with RemoveMessages in update"
    remove_msgs = update["messages"]
    assert len(remove_msgs) > 0

    # Apply the add_messages reducer to simulate what LangGraph does
    final_messages = add_messages(messages, remove_msgs)
    assert len(final_messages) < len(messages), (
        f"Expected trimmed state ({len(final_messages)}) < original ({len(messages)})"
    )
