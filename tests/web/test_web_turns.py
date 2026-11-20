"""
Starting Conversations and asking Follow-ups from the web, with live steps (ticket web-interface/04).

The app is served by uvicorn on the test's own event loop (the one checkpointer must not cross
loops), so the Server-Sent Events arrive over real HTTP as a browser gets them. The stand-in
model replies from a script per Conversation, keyed by its first question, and a reply may wait
for the test to release it (ADR-011: no live model).
"""

import asyncio
import json
import socket

import httpx
import pytest
import pytest_asyncio
import uvicorn
from _cli_harness import cli_run  # noqa: F401
from argon2 import PasswordHasher
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError

import agent.graph as graph_module
from agent.claude_code_model import ClaudeCodeError
from agent.graph import build_graph, get_checkpointer
from agent.memory.episodic import EpisodicMemory
from agent.tools.classification import read_tool, write_action
from agent.turn_rules import STEP_LIMIT_STOPPED
from agent.web import WebConfig, create_app

pytestmark = pytest.mark.asyncio

PASSWORD = "correct horse battery staple"
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


@read_tool
@tool("read_notes")
async def read_notes(topic: str) -> str:
    """Reads notes."""
    return f"notes about {topic}"


@write_action
@tool("send_mail")
async def send_mail(to: str) -> str:
    """Sends mail."""
    return "sent"


TOOLS = [read_notes, send_mail]


class Wait:
    """A scripted reply the model gives only once the test sets ``gate``."""
    def __init__(self, gate: asyncio.Event, reply):
        self.gate, self.reply = gate, reply


class StandInModel(GenericFakeChatModel):
    """Replies from ``scripts[first question]``, in order. A reply is an AIMessage, a string, an
    exception to raise, or a Wait."""
    scripts: dict
    disable_streaming: bool = True

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("async only")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        question = next(m.content for m in messages if isinstance(m, HumanMessage))
        reply = self.scripts[question].pop(0)
        if isinstance(reply, Wait):
            await reply.gate.wait()
            reply = reply.reply
        if isinstance(reply, BaseException):
            raise reply
        message = AIMessage(content=reply) if isinstance(reply, str) else reply
        return ChatResult(generations=[ChatGeneration(message=message)])


def ai(text, *calls):
    return AIMessage(content=text, tool_calls=[{"id": i, "name": n, "args": a} for i, n, a in calls])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Web:
    """The served app and a logged-in client on it."""
    def __init__(self, client, origin, app, db):
        self.client, self.origin, self.app, self.db = client, origin, app, db

    async def start(self, question):
        response = await self.client.post("/api/conversations", json={"question": question},
                                          headers={"Origin": self.origin})
        assert response.status_code == 201, response.text
        return response.json()["thread_id"]

    async def ask(self, thread_id, question):
        return await self.client.post(f"/api/conversations/{thread_id}/turns", json={"question": question},
                                      headers={"Origin": self.origin})

    def events(self, thread_id, headers=None):
        """An open event stream: ``async with web.events(t) as stream: await stream.next()``."""
        return EventStream(self.client, f"/api/conversations/{thread_id}/events",
                           headers if headers is not None else {"Origin": self.origin})


class EventStream:
    def __init__(self, client, url, headers):
        self.client, self.url, self.headers = client, url, headers

    async def __aenter__(self):
        self._cm = self.client.stream("GET", self.url, headers={"Accept": "text/event-stream", **self.headers})
        self.response = await self._cm.__aenter__()
        self._lines = self.response.aiter_lines()
        return self

    async def __aexit__(self, *exc):
        await self._cm.__aexit__(*exc)

    async def next(self, timeout=5):
        """The next event as (name, data)."""
        async def read():
            name, data = None, None
            async for line in self._lines:
                if line.startswith("event: "):
                    name = line[len("event: "):]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
                elif line == "" and name is not None:
                    return name, data
        return await asyncio.wait_for(read(), timeout)

    async def settled(self, timeout=5):
        """Every event until no turn runs: a ``state`` that is not running, or a ``turn_ended``."""
        seen = []
        while not seen or not (seen[-1][0] == "turn_ended"
                               or (seen[-1][0] == "state" and seen[-1][1]["status"] != "running")):
            seen.append(await self.next(timeout))
        return seen

    async def until(self, name, timeout=5):
        """Every event up to and including the first named ``name``."""
        seen = []
        while not seen or seen[-1][0] != name:
            seen.append(await self.next(timeout))
        return seen


@pytest_asyncio.fixture
async def serve(tmp_path, monkeypatch):
    """serve(scripts, langfuse_connected=False, tools=TOOLS) -> Web: the app on the Fixture tools, a stand-in
    model and a real checkpoint file, served on a free local port. The run log is a temp file."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    db = str(tmp_path / "hitl.db")
    memory = EpisodicMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(graph_module, "get_episodic_memory", lambda: memory)
    started = []

    async def make(scripts, *, langfuse_connected=False, logins=None, tools=TOOLS):
        port = free_port()
        origin = f"http://127.0.0.1:{port}"
        checkpointer_cm = get_checkpointer(db)
        checkpointer = await checkpointer_cm.__aenter__()
        model = StandInModel(messages=iter([]), scripts=scripts)
        app = create_app(
            graph=build_graph(checkpointer, tools, model), tools=tools, model=model, checkpoint_path=db,
            web=WebConfig(password_hash=FAST_HASHER.hash(PASSWORD), port=port, dist_dir=dist),
            langfuse_connected=langfuse_connected, logins=logins,
        )
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.01)
        client = httpx.AsyncClient(base_url=origin, timeout=10)
        assert (await client.post("/api/login", json={"password": PASSWORD},
                                  headers={"Origin": origin})).status_code == 200
        started.append((server, task, client, checkpointer_cm))
        web = Web(client, origin, app, db)
        web.memory = memory
        return web

    yield make
    for server, task, client, checkpointer_cm in started:
        await client.aclose()
        server.should_exit = server.force_exit = True
        await task
        await checkpointer_cm.__aexit__(None, None, None)


def names(events):
    return [name for name, _ in events]


async def test_starting_a_conversation_runs_its_first_question_and_lists_it_first(serve):
    web = await serve({
        "older": [ai("Old answer.")],
        "Read my tax notes": [ai("", ("c1", "read_notes", {"topic": "tax"})), ai("Here are your **notes**.")],
    })
    older = await web.start("older")
    async with web.events(older) as stream:
        await stream.settled()

    thread_id = await web.start("Read my tax notes")
    async with web.events(thread_id) as stream:
        events = await stream.settled()

    assert thread_id != older
    rows = (await web.client.get("/api/conversations")).json()
    assert [r["thread_id"] for r in rows] == [thread_id, older]
    assert rows[0]["title"] == "Read my tax notes"
    transcript = (await web.client.get(f"/api/conversations/{thread_id}")).json()
    assert transcript["turns"][0]["answer"] == "Here are your **notes**."
    assert events[-1][1]["status"] == "idle"
    # The first event is the current state; the turn shows its step and its answer.
    assert events[0][0] == "state"


async def test_tool_steps_arrive_live_in_order_and_the_answer_arrives_whole(serve):
    gate = asyncio.Event()
    web = await serve({"Read my tax notes": [
        Wait(gate, ai("", ("c1", "read_notes", {"topic": "tax"}), ("c2", "read_notes", {"topic": "vat"}))),
        ai("Both read."),
    ]})
    thread_id = await web.start("Read my tax notes")
    async with web.events(thread_id) as stream:
        name, state = await stream.next()
        assert (name, state["status"]) == ("state", "running")  # connected mid-turn
        gate.set()
        events = await stream.until("turn_ended")

    assert names(events) == ["step_started", "step_started", "step_finished", "step_finished", "answer", "turn_ended"]
    assert events[0][1]["step"] == {"id": "c1", "name": "read_notes", "args": {"topic": "tax"},
                                    "result": None, "error": False}
    assert [e[1]["step"]["result"] for e in events[2:4]] == ["notes about tax", "notes about vat"]
    assert events[4][1] == {"text": "Both read."}
    assert events[5][1] == {"status": "idle", "outcome": "answered", "message": None}


async def test_a_turn_parked_at_an_approval_sends_the_pending_card(serve):
    gate = asyncio.Event()
    web = await serve({"Mail Ann": [Wait(gate, ai("", ("w1", "send_mail", {"to": "ann@example.com"})))]})
    thread_id = await web.start("Mail Ann")
    async with web.events(thread_id) as stream:
        await stream.next()
        gate.set()
        events = await stream.until("turn_ended")

    assert names(events) == ["step_started", "approval_pending", "turn_ended"]
    pending = events[1][1]["pending"]
    assert pending["tool_call_ids"] == ["w1"]
    assert pending["interrupt_id"]
    assert events[2][1] == {"status": "awaiting_approval", "outcome": "approval", "message": None}


async def test_a_second_question_on_a_thread_with_a_running_turn_is_refused(serve):
    gate = asyncio.Event()
    web = await serve({"slow": [Wait(gate, ai("Done."))]})
    thread_id = await web.start("slow")

    response = await web.ask(thread_id, "another")

    assert response.status_code == 409
    gate.set()
    async with web.events(thread_id) as stream:
        await stream.settled()
    assert (await web.client.get(f"/api/conversations/{thread_id}")).json()["turns"][-1]["answer"] == "Done."


async def test_a_follow_up_continues_the_conversation(serve):
    web = await serve({"Hi": [ai("Hello."), ai("You said hi.")]})
    thread_id = await web.start("Hi")
    async with web.events(thread_id) as stream:
        await stream.settled()

        assert (await web.ask(thread_id, "What did I say?")).status_code == 202
        events = await stream.until("turn_ended")

    assert events[0] == ("turn_started", {"question": "What did I say?"})
    assert ("answer", {"text": "You said hi."}) in events
    turns = (await web.client.get(f"/api/conversations/{thread_id}")).json()["turns"]
    assert [t["question"] for t in turns] == ["Hi", "What did I say?"]


async def test_a_question_on_an_unknown_conversation_is_not_found(serve):
    web = await serve({})

    assert (await web.ask("nope", "hello")).status_code == 404


async def test_two_conversations_run_their_turns_at_the_same_time(serve):
    gate_a, gate_b = asyncio.Event(), asyncio.Event()
    web = await serve({"A": [Wait(gate_a, ai("Answer A."))], "B": [Wait(gate_b, ai("Answer B."))]})
    thread_a = await web.start("A")
    thread_b = await web.start("B")
    async with web.events(thread_a) as stream_a, web.events(thread_b) as stream_b:
        assert (await stream_a.next())[1]["status"] == "running"
        assert (await stream_b.next())[1]["status"] == "running"

        gate_b.set()  # B finishes while A still waits
        assert ("answer", {"text": "Answer B."}) in await stream_b.until("turn_ended")
        gate_a.set()
        assert ("answer", {"text": "Answer A."}) in await stream_a.until("turn_ended")


async def test_two_clients_on_one_thread_get_the_same_events_and_a_late_one_the_current_state_first(serve):
    first, second = asyncio.Event(), asyncio.Event()
    web = await serve({"Read": [
        Wait(first, ai("", ("c1", "read_notes", {"topic": "tax"}))),
        Wait(second, ai("Read.")),
    ]})
    thread_id = await web.start("Read")
    async with web.events(thread_id) as early:
        await early.next()
        first.set()
        await early.until("step_finished")
        async with web.events(thread_id) as late:
            name, state = await late.next()
            second.set()
            early_events = await early.until("turn_ended")
            late_events = await late.until("turn_ended")

    assert name == "state" and state["status"] == "running"
    (turn,) = state["transcript"]["turns"]
    assert turn["question"] == "Read"
    assert [(s["id"], s["result"]) for s in turn["steps"]] == [("c1", "notes about tax")]
    assert early_events == late_events
    assert names(late_events) == ["answer", "turn_ended"]


@pytest.mark.parametrize("failure, message", [
    (ClaudeCodeError("Claude Code is not logged in. Run: claude auth login"),
     "Stopped: Claude Code is not logged in. Run: claude auth login"),
    (GraphRecursionError("Recursion limit of 40 reached"), STEP_LIMIT_STOPPED),
])
async def test_a_known_failure_ends_the_turn_with_the_clis_message(serve, failure, message):
    gate = asyncio.Event()
    web = await serve({"Hi": [Wait(gate, failure)]})
    thread_id = await web.start("Hi")
    async with web.events(thread_id) as stream:
        await stream.next()
        gate.set()
        (event,) = await stream.until("turn_ended")

    assert event[1] == {"status": "idle", "outcome": "failed", "message": message}
    [run] = web.memory.get_recent_runs(10)
    assert run.thread_id == thread_id
    assert type(failure).__name__ in run.error_message


async def test_a_failed_turns_message_is_kept_across_reloads_and_never_reaches_the_model(serve):
    gate = asyncio.Event()
    web = await serve({"Hi": [Wait(gate, GraphRecursionError("Recursion limit of 40 reached")), ai("Recovered.")]})
    thread_id = await web.start("Hi")
    async with web.events(thread_id) as stream:
        await stream.next()
        gate.set()
        await stream.until("turn_ended")

    # A refresh or a new tab rebuilds the transcript from the checkpoint: the message is still there.
    assert (await web.client.get(f"/api/conversations/{thread_id}")).json()["turns"][0]["stopped"] == STEP_LIMIT_STOPPED
    async with web.events(thread_id) as stream:
        _, state = await stream.next()
        assert state["transcript"]["turns"][0]["stopped"] == STEP_LIMIT_STOPPED
        assert (await web.ask(thread_id, "Again")).status_code == 202
        await stream.until("turn_ended")

    turns = (await web.client.get(f"/api/conversations/{thread_id}")).json()["turns"]
    assert turns[0]["stopped"] == STEP_LIMIT_STOPPED and "stopped" not in turns[1]
    thread = (await web.app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})).values["messages"]
    assert not any(STEP_LIMIT_STOPPED in str(m.content) for m in thread)


async def test_an_unexpected_error_ends_the_turn_and_the_server_keeps_serving(serve):
    gate = asyncio.Event()
    web = await serve({"Hi": [Wait(gate, KeyError("boom")), ai("Recovered.")]})
    thread_id = await web.start("Hi")
    async with web.events(thread_id) as stream:
        await stream.next()
        gate.set()
        (event,) = await stream.until("turn_ended")

        assert event[1]["outcome"] == "error"
        assert "KeyError" in event[1]["message"]
        assert (await web.ask(thread_id, "Again")).status_code == 202
        assert ("answer", {"text": "Recovered."}) in await stream.until("turn_ended")


async def test_the_run_log_entry_is_rewritten_after_each_web_turn(serve):
    web = await serve({"First?": [ai("One."), ai("Two.")]})
    thread_id = await web.start("First?")
    async with web.events(thread_id) as stream:
        await stream.settled()
        [run] = web.memory.get_recent_runs(10)
        assert (run.thread_id, run.user_input, run.final_output) == (thread_id, "First?", "One.")

        await web.ask(thread_id, "Second?")
        await stream.until("turn_ended")

    [run] = web.memory.get_recent_runs(10)
    assert (run.thread_id, run.user_input, run.final_output) == (thread_id, "First?\nSecond?", "One.\nTwo.")


async def test_a_conversation_is_one_langfuse_trace_named_web_run_with_the_thread_id(serve, langfuse_spans):
    web = await serve({"Read": [ai("", ("c1", "read_notes", {"topic": "tax"})), ai("Read."), ai("Again.")]},
                      langfuse_connected=True)
    thread_id = await web.start("Read")
    async with web.events(thread_id) as stream:
        await stream.settled()
        await web.ask(thread_id, "Once more")
        await stream.until("turn_ended")

    spans = langfuse_spans()
    assert spans
    assert {f"{s.context.trace_id:032x}" for s in spans} == {thread_id.replace("-", "")}
    assert {s.attributes.get("langfuse.trace.name") for s in spans} == {"web-run"}
    assert "read_notes" in {s.name for s in spans}


async def test_a_conversation_started_on_the_web_continues_in_the_cli(serve, cli_run, capsys):
    web = await serve({"What is on today?": [ai("A dentist visit.")]})
    thread_id = await web.start("What is on today?")
    async with web.events(thread_id) as stream:
        await stream.settled()

    seen, start = cli_run

    def remembers(messages):
        asked = [m.content for m in messages if isinstance(m, HumanMessage)]
        return AIMessage(content=f"You asked: {asked}")

    await start([remembers], "--resume", thread_id, "And tomorrow?")

    out = capsys.readouterr().out
    assert f"Conversation {thread_id}" in out
    assert "You asked: ['What is on today?', 'And tomorrow?']" in out
