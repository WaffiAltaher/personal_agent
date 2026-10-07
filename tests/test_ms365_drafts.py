"""
tests/test_ms365_drafts.py

Inbox triage against the Fixture world (seam A): the graph runs with a scripted model and
the MS365 tools loaded over real MCP from the stand-in. The agent reads mail and proposes a
reply; the reply becomes a Draft in Outlook only after the owner approves it. Assertions are
on the Drafts the stand-in recorded and on what the model gets to see.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools import load_all_tools
from fixture_world.ms365 import DRAFT_FAILURE_ENV, DRAFTS_ENV, recorded_draft_calls, recorded_drafts

QUESTION_ID = "AAMkAGZpeHR1cmUAMESSAGE02"  # Jan de Bakker's question about invoice 2026-031
REPLY = "Hi Jan, happy to go through the hours on Tuesday. Kind regards, Jen"


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    """Keep the retry semantics but skip the real sleeps."""
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


@pytest.fixture
def drafts_file(tmp_path, monkeypatch):
    """A fresh Fixture world: no Drafts yet, the clock pinned to the seeded week."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-07")
    path = tmp_path / "drafts.jsonl"
    monkeypatch.setenv(DRAFTS_ENV, str(path))
    return path


@pytest.fixture
def start_triage(drafts_file, scripted_model):
    async def start(draft_call: dict, final_answer: str):
        """'Summarise Jan's mail about invoice 2026-031 and propose a reply': the model reads
        the mail, then calls a draft tool. Returns (graph, config, result) at the approval pause."""
        tools, notices = await load_all_tools(fixtures=True)
        assert notices == []
        model = scripted_model([
            _call("ms365_list-mail-messages", {"search": '"invoice 2026-031"', "select": "id,subject,from"}, "search"),
            _call("ms365_get-mail-message", {"messageId": QUESTION_ID}, "read"),
            _call(draft_call["name"], draft_call["args"], "draft"),
            AIMessage(content=final_answer),
        ])
        graph = build_graph(checkpointer=InMemorySaver(), tools=tools, model=model)
        config = {"configurable": {"thread_id": "triage"}}
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Summarise Jan's mail about invoice 2026-031 and propose a reply.")]},
            config=config,
        )
        return graph, config, result
    return start


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _tool_results(result: dict) -> dict[str, ToolMessage]:
    return {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}


def _payload(message: ToolMessage):
    content = message.content
    return json.loads(content if isinstance(content, str) else "".join(block["text"] for block in content))


REPLY_DRAFT = {"name": "ms365_create-reply-draft", "args": {"messageId": QUESTION_ID, "body": {"Comment": REPLY}}}


@pytest.mark.asyncio
async def test_approved_reply_becomes_a_draft(start_triage, drafts_file):
    graph, config, result = await start_triage(REPLY_DRAFT, "I saved a reply to Jan in your Drafts.")

    # Reading ran without approval; the Draft waits for the owner.
    assert "__interrupt__" in result
    assert "ms365_create-reply-draft" in result["__interrupt__"][0].value["actions"]
    assert _payload(_tool_results(result)["read"])["from"]["emailAddress"]["address"] == "jan@goudenbol.example"
    assert recorded_draft_calls(drafts_file) == []

    result = await graph.ainvoke(Command(resume="approve"), config=config)

    [draft] = recorded_drafts(drafts_file)
    assert draft["isDraft"] is True
    assert draft["subject"] == "RE: Questions about invoice 2026-031"
    assert [r["emailAddress"]["address"] for r in draft["toRecipients"]] == ["jan@goudenbol.example"]
    assert draft["body"]["content"].startswith(REPLY)
    assert draft["conversationId"] == "AAQkAGZpeHR1cmUACONV02"

    shown = _tool_results(result)["draft"]
    assert shown.status != "error"
    assert _payload(shown)["id"] == draft["id"]
    assert result["messages"][-1].content == "I saved a reply to Jan in your Drafts."


@pytest.mark.asyncio
async def test_new_draft_email_is_recorded_as_written(start_triage, drafts_file):
    message = {
        "subject": "Hours on invoice 2026-031",
        "body": {"contentType": "text", "content": REPLY},
        "toRecipients": [{"emailAddress": {"address": "jan@goudenbol.example"}}],
    }
    graph, config, _ = await start_triage({"name": "ms365_create-draft-email", "args": {"body": message}}, "Saved.")

    await graph.ainvoke(Command(resume="approve"), config=config)

    [draft] = recorded_drafts(drafts_file)
    assert {key: draft[key] for key in message} == message
    assert draft["isDraft"] is True
    assert draft["from"]["emailAddress"]["address"] == "jendo@example.com"


@pytest.mark.asyncio
async def test_rejected_reply_creates_no_draft_and_is_acknowledged(start_triage, drafts_file):
    graph, config, _ = await start_triage(REPLY_DRAFT, "Understood, I did not save the reply.")

    result = await graph.ainvoke(Command(resume="reject"), config=config)

    assert recorded_draft_calls(drafts_file) == []
    assert "rejected by the user" in _tool_results(result)["draft"].content
    assert result["messages"][-1].content == "Understood, I did not save the reply."


@pytest.mark.asyncio
async def test_transient_error_on_a_draft_call_is_not_retried(start_triage, drafts_file, monkeypatch):
    monkeypatch.setenv(DRAFT_FAILURE_ENV, "transient")
    graph, config, _ = await start_triage(REPLY_DRAFT, "Saving the draft failed; please check Outlook.")

    result = await graph.ainvoke(Command(resume="approve"), config=config)

    assert len(recorded_draft_calls(drafts_file)) == 1  # one attempt reached Outlook, no retry
    assert recorded_drafts(drafts_file) == []
    failure = _tool_results(result)["draft"]
    assert failure.status == "error"
    assert "503" in str(failure.content)
    assert result["messages"][-1].content == "Saving the draft failed; please check Outlook."
