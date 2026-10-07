"""
tests/test_capstone.py

The cross-domain capstone against the Fixture world (seam A): "which clients are overdue on
payment, and draft reminder emails". The graph runs with a scripted model and with the
Informer and MS365 tools loaded over real MCP, exactly as `--fixtures` loads them. The
scripted model plays an agent following the system prompt's rules: it reads the Overdue
invoices from Informer, proposes one Payment reminder Draft per Client in a single batch, and
reports the Clients it has no email address for. Assertions are on the Drafts the stand-in
recorded, the approval pause and what the owner is told, against the seeded figures.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools import load_all_tools
from fixture_world.ms365 import DRAFTS_ENV, recorded_draft_calls, recorded_drafts

ASK = "Which clients are overdue on payment? Draft reminder emails."
OVERDUE_CALL_ID = "overdue"
DRAFT_TOOL = "ms365_create-draft-email"


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
    """A fresh Fixture world: no Drafts yet, the clock pinned to the seeded Wednesday."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-07")
    path = tmp_path / "drafts.jsonl"
    monkeypatch.setenv(DRAFTS_ENV, str(path))
    return path


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _payload(message: ToolMessage):
    content = message.content
    return json.loads(content if isinstance(content, str) else "".join(block["text"] for block in content))


def _overdue_seen(messages) -> dict:
    """The Overdue invoices per Client, as the model was shown them by Informer."""
    [result] = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == OVERDUE_CALL_ID]
    assert result.status != "error"
    return _payload(result)


def _address(client: dict) -> str | None:
    return client["email_invoice"] or client["email"]


def draft_one_reminder_per_client(messages) -> AIMessage:
    """One Payment reminder per Client with an email address, all proposed in one batch."""
    overdue = _overdue_seen(messages)
    calls = []
    for client in overdue["clients"]:
        if not _address(client):
            continue
        lines = "\n".join(
            f"- Invoice {invoice['number']}, due {invoice['due_date']}: EUR {invoice['open_amount']}"
            for invoice in client["invoices"]
        )
        body = (
            f"Dear {client['name']},\n\nThe following invoices are past their due date:\n{lines}\n"
            f"Total open: EUR {client['total_open_amount']}\n\nKind regards,\nITtopia"
        )
        calls.append({
            "id": f"reminder-{client['relation_id']}",
            "name": DRAFT_TOOL,
            "args": {"body": {
                "subject": "Payment reminder: overdue invoices",
                "body": {"contentType": "text", "content": body},
                "toRecipients": [{"emailAddress": {"address": _address(client)}}],
            }},
        })
    return AIMessage(content="", tool_calls=calls)


def report_drafts_and_missing_addresses(messages) -> AIMessage:
    overdue = _overdue_seen(messages)
    drafted = [c["name"] for c in overdue["clients"] if _address(c)]
    missing = [c["name"] for c in overdue["clients"] if not _address(c)]
    return AIMessage(content=(
        f"I saved Payment reminders in your Drafts for: {', '.join(drafted)}. "
        f"No email address in Informer for: {', '.join(missing)}; please contact them yourself."
    ))


@pytest.fixture
def start_capstone(drafts_file, scripted_model):
    async def start(final_answer):
        """Runs the capstone up to the approval pause. Returns (graph, config, result, model)."""
        tools, notices = await load_all_tools(fixtures=True)
        assert notices == []
        model = scripted_model([
            _call("informer_list_overdue_invoices", {}, OVERDUE_CALL_ID),
            draft_one_reminder_per_client,
            final_answer,
        ])
        graph = build_graph(checkpointer=InMemorySaver(), tools=tools, model=model)
        config = {"configurable": {"thread_id": "capstone"}}
        result = await graph.ainvoke({"messages": [HumanMessage(content=ASK)]}, config=config)
        return graph, config, result
    return start


def _drafts_by_recipient(path) -> dict[str, dict]:
    drafts = {}
    for draft in recorded_drafts(path):
        [recipient] = [r["emailAddress"]["address"] for r in draft["toRecipients"]]
        drafts[recipient] = draft
    return drafts


@pytest.mark.asyncio
async def test_approved_reminders_become_one_draft_per_client(start_capstone, drafts_file):
    graph, config, result = await start_capstone(report_drafts_and_missing_addresses)

    # Informer was read without approval; the batch of Drafts waits for the owner.
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["actions"].count(DRAFT_TOOL) == 2
    assert recorded_draft_calls(drafts_file) == []

    result = await graph.ainvoke(Command(resume="approve"), config=config)

    drafts = _drafts_by_recipient(drafts_file)
    assert sorted(drafts) == ["facturen@goudenbol.example", "info@vandijklogistiek.example"]
    assert all(d["isDraft"] for d in drafts.values())

    gouden_bol = drafts["facturen@goudenbol.example"]["body"]["content"]
    assert "Invoice 2026-0101, due 2026-08-31: EUR 1210.00" in gouden_bol
    assert "Invoice 2026-0105, due 2026-09-14: EUR 305.00" in gouden_bol  # partially paid
    assert "2026-0110" not in gouden_bol  # due today: not yet overdue
    assert "Total open: EUR 1515.00" in gouden_bol

    van_dijk = drafts["info@vandijklogistiek.example"]["body"]["content"]
    assert "Invoice 2026-0102, due 2026-09-01: EUR 100.10" in van_dijk
    assert "Invoice 2026-0103, due 2026-09-10: EUR 200.20" in van_dijk
    assert "2026-0098" not in van_dijk  # paid
    assert "Total open: EUR 300.30" in van_dijk

    # The Client without an email address gets no Draft and is reported to the owner.
    assert not any("Noordzee" in d["body"]["content"] for d in drafts.values())
    assert "No email address in Informer for: Noordzee Advies" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_rejected_reminders_create_no_drafts(start_capstone, drafts_file):
    graph, config, _ = await start_capstone("Understood, I did not save the reminders.")

    result = await graph.ainvoke(Command(resume="reject"), config=config)

    assert recorded_draft_calls(drafts_file) == []
    rejections = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id.startswith("reminder-")]
    assert len(rejections) == 2
    assert all("rejected by the user" in m.content for m in rejections)
    assert result["messages"][-1].content == "Understood, I did not save the reminders."


@pytest.mark.asyncio
async def test_the_model_is_told_the_ittopia_rules(scripted_model):
    """The default system prompt carries the ITtopia rules the capstone relies on."""
    seen = {}

    def answer(messages) -> AIMessage:
        seen["system"] = messages[0]
        return AIMessage(content="ok")

    graph = build_graph(tools=[], model=scripted_model([answer]))
    await graph.ainvoke({"messages": [HumanMessage(content=ASK)]})

    system = seen["system"]
    assert isinstance(system, SystemMessage)
    for rule in (
        "ITtopia",
        "never send",
        "one Payment reminder per Client",
        "without an email address",
        "MS365, not Gmail",
        "Informer",
    ):
        assert rule in system.content, rule
