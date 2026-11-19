"""Ticket 12: remember on approval and an honest episodic run log."""

from datetime import date
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.conversation import run_conversation
from agent.graph import build_graph, log_run_to_memory
from agent.config import settings
from agent.memory.episodic import EpisodicMemory, RunRecord
from agent.memory.semantic import SemanticMemory
from agent.tools.classification import read_tool, write_action


class _FakeEmbeddings:
    _VEC: list[float] = [1.0] + [0.0] * 15

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._VEC for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._VEC


@pytest.fixture
def episodic(tmp_path, monkeypatch):
    db_path = str(tmp_path / "episodic.db")
    mem = EpisodicMemory(db_path=db_path)
    monkeypatch.setattr("agent.graph.get_episodic_memory", lambda: mem)
    monkeypatch.setattr("agent.memory.get_episodic_memory", lambda: mem)
    yield mem
    mem.close()


@pytest.fixture
def semantic(tmp_path, monkeypatch):
    with patch(
        "agent.memory.semantic.create_embeddings",
        return_value=_FakeEmbeddings(),
    ):
        mem = SemanticMemory(persist_dir=str(tmp_path / "chroma"))
    monkeypatch.setattr("agent.memory.get_semantic_memory", lambda: mem)
    monkeypatch.setattr("agent.tools.memory.get_semantic_memory", lambda: mem)
    yield mem


def _usage(prompt: int, completion: int) -> dict:
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": prompt + completion,
    }


@pytest.mark.asyncio
async def test_remember_pauses_for_approval_and_stores_only_when_approved(
    scripted_model, episodic, semantic, monkeypatch
):
    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    stored: list[str] = []

    @write_action
    @tool("remember")
    def remember(fact: str) -> str:
        """Store a long-term memory."""
        semantic.remember(fact)
        stored.append(fact)
        return "Stored."

    tools = [remember]

    def graph_for_run():
        return build_graph(
            checkpointer=InMemorySaver(),
            tools=tools,
            model=scripted_model(
                [
                    AIMessage(
                        content="",
                        tool_calls=[{"id": "m1", "name": "remember", "args": {"fact": "VAT is 21% in NL"}}],
                    ),
                    AIMessage(content="Done."),
                ]
            ),
        )

    config = {"configurable": {"thread_id": "remember-approve"}}
    graph = graph_for_run()
    first = await run_conversation(graph, config, tools=tools, user_message="remember VAT")
    assert "__interrupt__" in first
    assert stored == []

    await run_conversation(graph, config, tools=tools, resume_decision="reject")
    assert stored == []
    assert semantic.search_memories("VAT", k=5) == []

    config2 = {"configurable": {"thread_id": "remember-approve-2"}}
    graph2 = graph_for_run()
    await run_conversation(graph2, config2, tools=tools, user_message="remember VAT")
    await run_conversation(graph2, config2, tools=tools, resume_decision="approve")
    assert stored == ["VAT is 21% in NL"]
    hits = semantic.search_memories("VAT rate Netherlands", k=5)
    assert hits and "21%" in hits[0].content


@pytest.mark.asyncio
async def test_completed_run_without_remember_writes_nothing_to_semantic_memory(
    scripted_model, episodic, semantic, monkeypatch
):
    monkeypatch.setattr(settings, "memory_score_threshold", 0.0)
    @read_tool
    @tool("read_notes")
    async def read_notes() -> str:
        """Read notes."""
        return "notes"

    tools = [read_notes]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model(
            [
                AIMessage(content="", tool_calls=[{"id": "r1", "name": "read_notes", "args": {}}]),
                AIMessage(content="Here are your notes."),
            ]
        ),
    )
    config = {"configurable": {"thread_id": "no-auto-memory"}}
    result = await run_conversation(graph, config, tools=tools, user_message="show notes")
    log_run_to_memory(
        result,
        "show notes",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )

    assert semantic.search_memories("notes", k=5) == []
    assert episodic.get_recent_runs(1)[0].user_input == "show notes"


def test_run_log_usage_is_summed_over_every_model_call(episodic):
    messages = [
        AIMessage(content="step one", usage_metadata=_usage(100, 10)),
        AIMessage(content="step two", usage_metadata=_usage(50, 5)),
    ]
    log_run_to_memory(
        {"messages": messages},
        "multi-step question",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )
    saved = episodic.get_recent_runs(1)[0]
    assert saved.token_usage == {"prompt": 150, "completion": 15, "total": 165}
    assert saved.cost_usd == pytest.approx(0.00016875)  # 150 in + 15 out at 2026-10-07 Gemini rates


def test_run_log_treats_only_the_exact_step_limit_answer_as_step_limit(episodic):
    from agent.graph import STEP_LIMIT_ANSWER

    log_run_to_memory(
        {"messages": [AIMessage(content=STEP_LIMIT_ANSWER, usage_metadata=_usage(5, 1))]},
        "loop",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )
    assert episodic.get_recent_runs(1)[0].outcome == "step limit"

    log_run_to_memory(
        {
            "messages": [
                AIMessage(
                    content="I stopped because of the step limit you configured.",
                    usage_metadata=_usage(5, 1),
                )
            ]
        },
        "mention",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )
    assert episodic.get_recent_runs(1)[0].outcome == "completed"


def test_run_log_records_rejected_and_error_outcomes(episodic):
    rejected_messages = [
        AIMessage(content="", tool_calls=[{"id": "w1", "name": "send_mail", "args": {}}]),
        ToolMessage(
            content="Action 'send_mail' was rejected by the user. cancelled.",
            tool_call_id="w1",
            status="error",
        ),
        AIMessage(content="Cancelled.", usage_metadata=_usage(20, 4)),
    ]
    log_run_to_memory(
        {"messages": rejected_messages},
        "send something",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
    )
    assert episodic.get_recent_runs(1)[0].outcome == "rejected"

    log_run_to_memory(
        {"messages": [AIMessage(content="partial", usage_metadata=_usage(10, 2))]},
        "crash question",
        model_name="google_genai:gemini-3.8-flash",
        run_date=date(2026, 10, 7),
        error="RuntimeError: boom",
    )
    assert episodic.get_recent_runs(1)[0].outcome == "error"
    assert episodic.get_recent_runs(1)[0].error_message == "RuntimeError: boom"


def test_run_log_write_failure_is_logged_not_raised(episodic, caplog):
    def boom(_run: RunRecord) -> str:
        raise OSError("disk full")

    episodic.log_run = boom  # type: ignore[method-assign]
    with caplog.at_level("WARNING"):
        log_run_to_memory(
            {"messages": [AIMessage(content="ok", usage_metadata=_usage(1, 1))]},
            "question",
            model_name="google_genai:gemini-3.8-flash",
            run_date=date(2026, 10, 7),
        )
    assert any("disk full" in r.message for r in caplog.records)
