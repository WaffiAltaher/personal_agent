"""
The Conversation list and transcript endpoints (ticket web-interface/03), on a checkpoint file
written the way the CLI writes it: a real SQLite file, a compiled graph and a stand-in model
(ADR-011). The app is called in-process on the test's own event loop, so the one checkpointer
serves the seeding and the app, as it does in the server.
"""

import time

import httpx
import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent.conversation import run_conversation
from agent.graph import build_graph, get_checkpointer
from agent.tools.classification import read_tool, write_action
from agent.web import WebConfig, create_app

pytestmark = pytest.mark.asyncio

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
PASSWORD = "correct horse battery staple"
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


@read_tool
@tool("read_notes")
async def read_notes(topic: str) -> str:
    """Reads notes."""
    return f"notes about {topic} <b>bold</b>"


@write_action
@tool("send_mail")
async def send_mail(to: str) -> str:
    """Sends mail."""
    return "sent"


TOOLS = [read_notes, send_mail]


def config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


@pytest_asyncio.fixture
async def world(tmp_path, scripted_model):
    """(ask, client): ask(thread_id, question, *replies) runs one turn on the checkpoint file;
    client is logged in to the app that reads the same file."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    db = str(tmp_path / "hitl.db")
    model = scripted_model([])

    async with get_checkpointer(db) as checkpointer:
        graph = build_graph(checkpointer, TOOLS, model)

        async def ask(thread_id, question, *scripted):
            model.messages = iter(scripted)
            return await run_conversation(graph, config(thread_id), tools=TOOLS, user_message=question)

        app = create_app(
            graph=graph, tools=TOOLS, model=model, checkpoint_path=db,
            web=WebConfig(password_hash=FAST_HASHER.hash(PASSWORD), port=PORT, dist_dir=dist),
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            await client.post("/api/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN})
            yield ask, client


def ai(text, calls=()):
    return AIMessage(content=text, tool_calls=[{"id": i, "name": n, "args": a} for i, n, a in calls])


async def test_the_list_needs_a_session(world):
    _, client = world
    client.cookies.clear()

    assert (await client.get("/api/conversations")).status_code == 401
    assert (await client.get("/api/conversations/t1")).status_code == 401


async def test_a_conversation_is_listed_by_its_first_question_with_its_date(world):
    ask, client = world
    before = time.time()
    await ask("t1", "What is on my calendar?", ai("Nothing today."))
    await ask("t1", "And tomorrow?", ai("A dentist visit."))

    rows = (await client.get("/api/conversations")).json()

    assert [(r["thread_id"], r["title"]) for r in rows] == [("t1", "What is on my calendar?")]
    assert before - 1 <= rows[0]["updated_at"] <= time.time() + 1  # epoch seconds of the latest checkpoint


async def test_a_long_first_question_is_cut_to_about_80_characters(world):
    ask, client = world
    await ask("t1", "x" * 200, ai("ok"))

    (row,) = (await client.get("/api/conversations")).json()

    assert row["title"] == "x" * 79 + "…"


async def test_the_list_is_newest_activity_first(world):
    ask, client = world
    await ask("old", "first thread", ai("a"))
    await ask("new", "second thread", ai("b"))
    await ask("old", "follow-up", ai("c"))

    rows = (await client.get("/api/conversations")).json()

    assert [r["thread_id"] for r in rows] == ["old", "new"]


async def test_the_list_stays_fast_with_several_hundred_threads(world):
    ask, client = world
    for n in range(300):
        await ask(f"t{n}", f"question {n}", ai(f"answer {n}"))

    started = time.perf_counter()
    rows = (await client.get("/api/conversations")).json()
    elapsed = time.perf_counter() - started

    assert len(rows) == 300
    assert rows[0]["thread_id"] == "t299"
    assert elapsed < 2


async def test_a_transcript_has_every_turn_with_its_tool_steps(world):
    ask, client = world
    await ask("t1", "Find my notes", ai("", [("c1", "read_notes", {"topic": "tax"})]), ai("Here they are."))
    await ask("t1", "Thanks", ai("You're welcome."))

    body = (await client.get("/api/conversations/t1")).json()

    assert body["thread_id"] == "t1"
    assert body["pending"] is None
    first, second = body["turns"]
    assert first["question"] == "Find my notes"
    assert first["answer"] == "Here they are."
    assert first["steps"] == [{
        "id": "c1", "name": "read_notes", "args": {"topic": "tax"},
        "result": "notes about tax <b>bold</b>", "error": False,
    }]
    assert (second["question"], second["answer"], second["steps"]) == ("Thanks", "You're welcome.", [])


async def test_an_answer_with_html_is_returned_as_text(world):
    ask, client = world
    await ask("t1", "hi", ai("<script>alert(1)</script> **bold**"))

    body = (await client.get("/api/conversations/t1")).json()

    assert body["turns"][0]["answer"] == "<script>alert(1)</script> **bold**"


async def test_a_thread_parked_at_an_approval_shows_the_pending_card(world):
    ask, client = world
    await ask("t1", "Mail Ann", ai("", [("w1", "send_mail", {"to": "ann@example.com"})]))

    body = (await client.get("/api/conversations/t1")).json()

    (turn,) = body["turns"]
    assert turn["question"] == "Mail Ann"
    assert turn["answer"] is None
    assert turn["steps"] == [{"id": "w1", "name": "send_mail", "args": {"to": "ann@example.com"},
                              "result": None, "error": False}]
    pending = body["pending"]
    assert pending["tool_call_ids"] == ["w1"]
    assert "send_mail" in pending["actions"]
    assert pending["message"]
    assert pending["interrupt_id"]


async def test_an_unknown_thread_is_not_found(world):
    _, client = world

    assert (await client.get("/api/conversations/nope")).status_code == 404
