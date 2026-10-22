"""Ticket 22: stable prompt prefix, Anthropic cache marks, cached usage in run log."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver

from agent.conversation import run_conversation
from agent.graph import build_graph, log_run_to_memory
from agent.evals.efficiency import efficiency
from agent.memory.run_log import build_run_record
from agent.model_binding import (
    CACHE_BREAKPOINT,
    anthropic_system_message,
    bind_agent_tools,
    bound_tool_names,
)
from agent.tools.classification import read_tool, write_action

LOCAL = ZoneInfo("Europe/Amsterdam")


def _system_collector(seen: list):
    def reply(messages):
        seen.append(messages[0].content)
        if len(seen) == 1:
            return AIMessage(
                content="",
                tool_calls=[{"id": "t1", "name": "read_notes", "args": {}}],
            )
        return AIMessage(content="done.")

    return reply


@pytest.mark.asyncio
async def test_system_prompt_is_byte_identical_across_model_calls_in_one_run(
    scripted_model, monkeypatch
):
    """The runtime clock is fixed for the run, so the system block never shifts mid-run."""
    times = [
        datetime(2026, 3, 1, 8, 0, tzinfo=LOCAL),
        datetime(2026, 9, 15, 22, 45, tzinfo=LOCAL),
    ]
    seen_systems: list = []

    class _Clock:
        @classmethod
        def now(cls, tz=None):
            return times[min(len(seen_systems), len(times) - 1)]

        @classmethod
        def combine(cls, *args, **kwargs):
            return datetime.combine(*args, **kwargs)

        @classmethod
        def fromisoformat(cls, s):
            return datetime.fromisoformat(s)

    import agent.graph as graph_mod

    monkeypatch.setattr(graph_mod, "datetime", _Clock)

    @read_tool
    @tool("read_notes")
    async def read_notes() -> str:
        """Read notes."""
        return "notes"

    tools = [read_notes]
    graph = build_graph(
        model=scripted_model([_system_collector(seen_systems)] * 2),
        tools=tools,
    )
    await graph.ainvoke({"messages": [HumanMessage(content="multi-step")]})

    assert len(seen_systems) == 2
    assert seen_systems[0] == seen_systems[1]
    assert "2026-03-01T08:00:00" in seen_systems[0]


@pytest.mark.asyncio
async def test_resumed_run_keeps_the_original_runtime_clock(scripted_model, monkeypatch):
    seen: list = []

    def first(messages):
        seen.append(messages[0].content)
        return AIMessage(
            content="",
            tool_calls=[{"id": "w1", "name": "send_mail", "args": {"to": "a@example.com"}}],
        )

    def second(messages):
        seen.append(messages[0].content)
        return AIMessage(content="Cancelled.")

    times = [
        datetime(2026, 1, 10, 11, 0, tzinfo=LOCAL),
        datetime(2026, 12, 24, 23, 59, tzinfo=LOCAL),
    ]

    class _Clock:
        @classmethod
        def now(cls, tz=None):
            return times[min(len(seen), len(times) - 1)]

        @classmethod
        def combine(cls, *args, **kwargs):
            return datetime.combine(*args, **kwargs)

        @classmethod
        def fromisoformat(cls, s):
            return datetime.fromisoformat(s)

    import agent.graph as graph_mod

    monkeypatch.setattr(graph_mod, "datetime", _Clock)

    @write_action
    @tool("send_mail")
    def send_mail(to: str) -> str:
        """Send mail."""
        return "sent"

    tools = [send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([first, second]),
    )
    config = {"configurable": {"thread_id": "resume-clock"}}
    first_result = await run_conversation(graph, config, tools=tools, user_message="send")
    assert "__interrupt__" in first_result
    await run_conversation(graph, config, tools=tools, resume_decision="reject")

    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert "2026-01-10T11:00:00" in seen[0]


def test_tools_are_bound_sorted_by_name():
    @tool("zebra")
    def zebra() -> str:
        """z"""
        return "z"

    @tool("alpha")
    def alpha() -> str:
        """a"""
        return "a"

    @tool("middle")
    def middle() -> str:
        """m"""
        return "m"

    model = ChatAnthropic(model="claude-sonnet-5-5", api_key="sk-ant-test")
    bound = bind_agent_tools(model, [zebra, middle, alpha])
    assert bound_tool_names(bound) == ["alpha", "middle", "zebra"]


def test_anthropic_request_marks_tools_and_system_prompt_cacheable():
    captured: dict = {}

    class CaptureAnthropic(ChatAnthropic):
        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            captured["payload"] = super()._get_request_payload(input_, stop=stop, **kwargs)
            raise RuntimeError("stop before HTTP")

    @tool("beta")
    def beta() -> str:
        """b"""
        return "b"

    @tool("alpha")
    def alpha() -> str:
        """a"""
        return "a"

    model = CaptureAnthropic(model="claude-sonnet-5-5", api_key="sk-ant-test")
    bound = bind_agent_tools(model, [beta, alpha])
    system = anthropic_system_message("system body")
    with pytest.raises(RuntimeError, match="stop before HTTP"):
        bound.invoke([system, HumanMessage("hi")])

    payload = captured["payload"]
    tools = payload["tools"]
    assert tools[-1]["name"] == "beta"
    assert tools[-1]["cache_control"] == CACHE_BREAKPOINT
    assert payload["system"][-1]["cache_control"] == CACHE_BREAKPOINT


def test_gemini_binding_adds_no_cache_marks():
    captured: dict = {}

    class CaptureGemini(ChatGoogleGenerativeAI):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            captured["kwargs"] = kwargs
            captured["messages"] = messages
            from langchain_core.outputs import ChatGeneration, ChatResult

            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    @tool("beta")
    def beta() -> str:
        """b"""
        return "b"

    model = CaptureGemini(model="gemini-3.8-flash", google_api_key="test-key")
    bound = bind_agent_tools(model, [beta])
    bound.invoke([SystemMessage("system body"), HumanMessage("hi")])

    assert "cache_control" not in str(captured.get("kwargs", {}))
    sys_msg = captured["messages"][0]
    assert sys_msg.content == "system body"


def test_run_log_records_cached_input_tokens_separately_and_prices_them(episodic):
    usage = {
        "input_tokens": 1_000,
        "output_tokens": 100,
        "total_tokens": 1_100,
        "input_token_details": {"cache_read": 400},
    }
    messages = [AIMessage(content="answer", usage_metadata=usage)]
    log_run_to_memory(
        {"messages": messages},
        "cached question",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )
    saved = episodic.get_recent_runs(1)[0]
    assert saved.token_usage == {
        "prompt": 1_000,
        "cached_input": 400,
        "completion": 100,
        "total": 1_100,
    }
    # 600 uncached × 0.75 + 400 cached × 0.075 + 100 out × 3.75, per 1M
    assert saved.cost_usd == pytest.approx(0.000855)


def test_eval_usage_records_cached_input_separately():
    usage_by_model = {
        "google_genai:gemini-3.8-flash": {
            "input_tokens": 1_000,
            "output_tokens": 100,
            "total_tokens": 1_100,
            "input_token_details": {"cache_read": 400},
        }
    }
    eff = efficiency(usage_by_model, latency_s=1.0, on=date(2026, 10, 7))
    model_usage = eff.by_model["google_genai:gemini-3.8-flash"]
    assert model_usage.cached_input_tokens == 400
    assert model_usage.cost_usd == pytest.approx(0.000855)


def test_build_run_record_sums_cached_tokens_over_model_calls():
    messages = [
        AIMessage(
            content="one",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "input_token_details": {"cache_read": 30},
            },
        ),
        AIMessage(
            content="two",
            usage_metadata={
                "input_tokens": 50,
                "output_tokens": 5,
                "total_tokens": 55,
                "input_token_details": {"cache_read": 20},
            },
        ),
    ]
    record = build_run_record(
        {"messages": messages},
        "q",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )
    assert record.token_usage["cached_input"] == 50
    assert record.token_usage["prompt"] == 150


@pytest.fixture
def episodic(tmp_path, monkeypatch):
    from agent.memory.episodic import EpisodicMemory

    mem = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))
    monkeypatch.setattr("agent.graph.get_episodic_memory", lambda: mem)
    monkeypatch.setattr("agent.memory.get_episodic_memory", lambda: mem)
    yield mem
    mem.close()
