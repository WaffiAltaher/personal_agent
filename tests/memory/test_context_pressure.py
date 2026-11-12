"""ADR-013: shrink the model view, never graph state."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import settings
from agent.conversation import run_conversation
from agent.graph import build_graph, check_context_budget
from agent.memory.budget import ContextBudgetManager, TokenCounter
from agent.memory.context_view import (
    _message_content_tokens,
    build_model_view,
    cap_tool_result_content,
    estimate_context_tokens,
)
from agent.memory.semantic import MemoryChunk
from agent.tools.memory import retrieve_memory
from agent.tools.classification import read_tool

SMALL_CLEAR_THRESHOLD = 800
SMALL_CLEAR_TARGET = 400
SMALL_TOOL_CAP = 50
SMALL_MEMORY_BUDGET = 120


@pytest.fixture
def small_context_limits(monkeypatch):
    monkeypatch.setattr(settings, "context_clear_threshold", SMALL_CLEAR_THRESHOLD)
    monkeypatch.setattr(settings, "context_clear_target", SMALL_CLEAR_TARGET)
    monkeypatch.setattr(settings, "tool_result_max_tokens", SMALL_TOOL_CAP)
    monkeypatch.setattr(settings, "memory_budget", SMALL_MEMORY_BUDGET)


def _chars_for_tokens(n: int) -> str:
    return "x" * (n * 4)


def test_state_never_loses_messages_when_context_is_huge(small_context_limits):
    """Nothing is ever removed from state, however large the context."""
    huge = HumanMessage(content=_chars_for_tokens(500))
    old_tool = ToolMessage(content=_chars_for_tokens(500), tool_call_id="t0", name="ping")
    messages = [
        HumanMessage(content="keep this question"),
        AIMessage(content="", tool_calls=[{"id": "t0", "name": "ping", "args": {"q": _chars_for_tokens(20)}}]),
        old_tool,
        huge,
    ]
    for i, msg in enumerate(messages):
        if not getattr(msg, "id", None):
            object.__setattr__(msg, "id", f"id-{i}")

    state = {"messages": messages, "token_usage_estimate": None}
    update = check_context_budget(state)

    assert "messages" not in update or update.get("messages") in (None, [])
    assert len(messages) == 4


def test_reduced_view_keeps_first_user_message_and_answers_every_tool_call(small_context_limits):
    first_question = "What did I ask?"
    big = _chars_for_tokens(850)
    messages = [
        HumanMessage(content=first_question),
        AIMessage(content="searching", tool_calls=[{"id": "a1", "name": "search", "args": {}}]),
        ToolMessage(content=big, tool_call_id="a1", name="search"),
        AIMessage(content="done"),
        HumanMessage(content="follow up"),
        AIMessage(content="again", tool_calls=[{"id": "a2", "name": "search", "args": {}}]),
        ToolMessage(content=big, tool_call_id="a2", name="search"),
    ]
    system = "system prompt"
    view, stubbed = build_model_view(
        messages,
        system_text=system,
        tools=[],
        last_model_input_tokens=None,
        message_count_at_last_model_call=0,
    )

    assert view, "view must not be empty"
    assert isinstance(view[0], SystemMessage)
    assert view[1].content == first_question
    assert stubbed, "large tool results must be stubbed above the threshold"

    tool_ids = {
        tc["id"]
        for msg in view
        if isinstance(msg, AIMessage)
        for tc in (msg.tool_calls or [])
    }
    answered = {m.tool_call_id for m in view if isinstance(m, ToolMessage)}
    assert tool_ids == answered


def test_oversized_tool_result_is_truncated_with_marker(small_context_limits):
    raw = _chars_for_tokens(300)
    capped = cap_tool_result_content(raw)
    assert len(capped) // 4 <= SMALL_TOOL_CAP
    assert "truncated" in capped.lower()


def test_three_hundred_k_token_tool_result_is_truncated_with_marker(monkeypatch):
    monkeypatch.setattr(settings, "tool_result_max_tokens", 300_000)
    raw = _chars_for_tokens(300_001)
    capped = cap_tool_result_content(raw)
    assert len(capped) // 4 <= 300_000
    assert "truncated" in capped.lower()


@pytest.mark.asyncio
async def test_run_continues_after_truncating_a_huge_tool_result(scripted_model, small_context_limits):
    @read_tool
    @tool
    async def blob() -> str:
        """Return a huge blob."""
        return _chars_for_tokens(300)

    def answer(_messages):
        last = _messages[-1]
        if isinstance(last, ToolMessage):
            assert "truncated" in last.content.lower()
            return AIMessage(content="ok")
        return AIMessage(content="", tool_calls=[{"id": "b1", "name": "blob", "args": {}}])

    tools = [blob]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([answer, answer]),
    )
    config = {"configurable": {"thread_id": "t-truncate"}}
    result = await run_conversation(graph, config, tools=tools, user_message="go")
    assert result["messages"][-1].content == "ok"


def test_new_user_turn_stubs_old_tool_results_on_first_model_call(small_context_limits):
    """First call after a new user message must stub earlier tool results over the threshold."""
    big = _chars_for_tokens(850)
    messages = [
        HumanMessage(content="first question"),
        AIMessage(content="", tool_calls=[{"id": "old1", "name": "search", "args": {}}]),
        ToolMessage(content=big, tool_call_id="old1", name="search"),
        AIMessage(content="answered earlier"),
        HumanMessage(content="follow up"),
    ]
    view, stubbed = build_model_view(
        messages,
        system_text="sys",
        tools=[],
        last_model_input_tokens=None,
        message_count_at_last_model_call=0,
    )
    old_tool = next(m for m in view if isinstance(m, ToolMessage) and m.tool_call_id == "old1")
    assert "result cleared" in old_tool.content
    assert big not in old_tool.content
    assert stubbed == {"old1"}


def test_after_reduction_next_estimate_stays_below_clear_threshold(small_context_limits):
    big = _chars_for_tokens(850)
    messages = [
        HumanMessage(content="q"),
        AIMessage(content="", tool_calls=[{"id": "o1", "name": "t", "args": {}}]),
        ToolMessage(content=big, tool_call_id="o1", name="t"),
        AIMessage(content="summary"),
    ]
    system = "sys"
    view, stubbed_ids = build_model_view(
        messages,
        system_text=system,
        tools=[],
        last_model_input_tokens=None,
        message_count_at_last_model_call=0,
    )
    cleared = next(m for m in view if isinstance(m, ToolMessage))
    assert "result cleared" in cleared.content

    view_tokens = estimate_context_tokens(
        state_messages=messages,
        system_text=system,
        tools=[],
        last_model_input_tokens=None,
        message_count_at_last_model_call=0,
    )
    assert view_tokens > SMALL_CLEAR_THRESHOLD
    reduced_total = sum(
        _message_content_tokens(m)
        for m in view
        if not isinstance(m, SystemMessage)
    ) + len(system) // 4
    assert reduced_total <= SMALL_CLEAR_TARGET

    second_pass, second_stubbed = build_model_view(
        messages,
        system_text=system,
        tools=[],
        last_model_input_tokens=reduced_total,
        message_count_at_last_model_call=len(messages),
        stubbed_tool_call_ids=stubbed_ids,
    )
    tool_in_view = next(m for m in second_pass if isinstance(m, ToolMessage))
    assert big not in tool_in_view.content
    assert "result cleared" in tool_in_view.content
    assert second_stubbed == stubbed_ids


def test_estimate_counts_assistant_reply_since_reported_input():
    """Delta must include the AIMessage added after the reported input token count."""
    reported_input = 10_000
    reply_token_estimate = 37
    reply = AIMessage(content="z" * (reply_token_estimate * 4))
    messages = [HumanMessage(content="question"), reply]
    pre_call_message_count = 1

    total = estimate_context_tokens(
        state_messages=messages,
        system_text="",
        tools=[],
        last_model_input_tokens=reported_input,
        message_count_at_last_model_call=pre_call_message_count,
    )
    assert total == reported_input + reply_token_estimate


def test_token_count_includes_system_tools_and_tool_call_arguments(small_context_limits):
    @tool
    def sample(x: str) -> str:
        """Sample tool."""
        return x

    tools = [sample]
    system = _chars_for_tokens(30)
    messages = [
        HumanMessage(content="hi"),
        AIMessage(
            content="call",
            tool_calls=[{"id": "c1", "name": "sample", "args": {"x": _chars_for_tokens(40)}}],
        ),
    ]
    total = estimate_context_tokens(
        state_messages=messages,
        system_text=system,
        tools=tools,
        last_model_input_tokens=None,
        message_count_at_last_model_call=0,
    )
    without_extras = TokenCounter().count_messages(messages)["total"] + len(system) // 4
    assert total > without_extras


def test_memory_retrieval_stops_at_budget(small_context_limits, monkeypatch):
    import agent.memory

    chunks = [
        MemoryChunk(content=_chars_for_tokens(40), source="documents", score=0.95),
        MemoryChunk(content=_chars_for_tokens(40), source="documents", score=0.90),
        MemoryChunk(content=_chars_for_tokens(40), source="documents", score=0.85),
    ]

    class FakeSemantic:
        def search_all(self, _query, k=5):
            return chunks

    monkeypatch.setattr(agent.memory, "_semantic", FakeSemantic())
    result = retrieve_memory.invoke({"query": "query"})
    selected = ContextBudgetManager().trim_memory_results(chunks, budget=SMALL_MEMORY_BUDGET)
    content_tokens = ContextBudgetManager().estimate_tokens("".join(c.content for c in selected))
    assert content_tokens <= SMALL_MEMORY_BUDGET
    assert len(selected) >= 1
    assert result.count("\n\n") + 1 == len(selected)


def test_clearing_reaches_the_target_when_the_provider_counts_more_tokens_than_the_estimate(small_context_limits):
    """The trigger is the provider's count; the stop condition must be in the same tokens. Dense
    content (JSON, non-English) can count several times its chars/4 estimate."""
    def turn(call_id: str, result: str) -> list:
        return [
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": call_id}]),
            ToolMessage(content=result, tool_call_id=call_id),
        ]

    old_result = _chars_for_tokens(150)
    messages = [HumanMessage(content="q"), *turn("a", old_result), *turn("b", old_result), *turn("c", "small")]
    # Estimated ~300 tokens (under the 400 target), but the provider reported four times that.
    reported = 1_200
    assert reported > SMALL_CLEAR_THRESHOLD

    view, stubbed = build_model_view(
        messages, system_text="", tools=[],
        last_model_input_tokens=reported, message_count_at_last_model_call=len(messages),
    )

    assert stubbed == {"a", "b"}  # before the fix: nothing was cleared
    assert all("result cleared" in m.content for m in view if isinstance(m, ToolMessage) and m.tool_call_id in "ab")
