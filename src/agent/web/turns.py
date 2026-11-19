"""
turns.py — turns of the web interface and their live events (ADR-018).

``Turns`` holds one ``ThreadState`` per Conversation the server has touched: its status (idle,
running, awaiting approval), its transcript as the tabs see it, and the queues of the tabs
watching it. A turn runs as its own task through the shared driver's streaming form
(``stream_conversation``), so turns on different threads run in parallel, while a thread takes
one turn at a time: a question sent while one runs is refused (``TurnRefused``).

Every event goes through ``ThreadState.publish``, which applies it to the thread's transcript and
puts it on every watching queue in the same step (no ``await`` between), so a tab that subscribes
mid-turn gets the current ``state`` and then exactly the events after it.

Events (name: data):
- ``state``: ``{status, transcript}`` (first on every stream; ``transcript`` as GET /conversations/{id});
  also sent mid-stream by a Stop that came before the turn's question reached the thread (while the
  turn waited on its login refresh, or abandoned a pending Approval), so the tab drops that turn as a
  reload does
- ``turn_started``: ``{question}``: a new turn with no steps and no answer (a Follow-up sent while an
  Approval waits: after ``approval_decided`` and the events that end the earlier turn)
- ``step_started``: ``{step}``: a tool call the model made (``result`` null)
- ``step_finished``: ``{step}``: that call with its ``result`` and ``error``
- ``approval_pending``: ``{pending}``: the Approval the turn parked at (as the transcript's ``pending``)
- ``approval_decided``: ``{interrupt_id, decision}``: that Approval was answered (``approve`` | ``reject``)
- ``answer``: ``{text}``: the turn's answer, whole
- ``turn_ended``: ``{status, outcome, message}``: outcome ``answered`` | ``approval`` | ``failed`` |
  ``error`` | ``cancelled`` (Stop); ``message`` is what the CLI would print for a failure or a Stop, else null
- ``login_status``: ``{logins}``: the login status strip changed (``Logins.status()``); sent on every
  Conversation's stream, as it is not about one Conversation

A turn first rechecks the logins (``Logins.refresh_for_turn``, bounded by its short wait), then
runs on the graph and tools bound at that moment: tools an MCP server brings once its login
passes (``add_tools``) rebuild the graph for later turns, and a turn already running keeps its own.
"""

import asyncio
import copy
import logging
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, ToolMessage
from langfuse import propagate_attributes
from langgraph.errors import GraphRecursionError

from agent.claude_code_model import ClaudeCodeError
from agent.cli import STEP_LIMIT_STOPPED, write_run_log
from agent.config import settings
from agent.conversation import APPROVAL_ABANDONED, close_interrupted_turn, stream_conversation
from agent.graph import build_graph
from agent.tracing import get_callback_handler
from agent.web.conversations import message_text, pending_approval, tool_step, transcript
from agent.web.logins import Logins

logger = logging.getLogger(__name__)

IDLE, RUNNING, AWAITING_APPROVAL = "idle", "running", "awaiting_approval"
STOPPED_BY_OWNER = "Interrupted."  # what the CLI prints after Ctrl-C cancels a turn


class TurnRefused(Exception):
    """A turn the thread can't take now (one is running, or a decision answers no pending Approval)."""


def apply_event(conversation: dict, name: str, data: dict) -> None:
    """Patch a transcript with one event, as the React app does."""
    turns = conversation["turns"]
    if name == "state":
        conversation.clear()
        conversation.update(copy.deepcopy(data["transcript"]))
    elif name == "turn_started":
        turns.append({"question": data["question"], "steps": [], "answer": None})
        conversation["pending"] = None
    elif name == "step_started":
        turns[-1]["steps"].append(data["step"])
    elif name == "step_finished":
        steps = turns[-1]["steps"]
        at = next((i for i, s in enumerate(steps) if s["id"] == data["step"]["id"]), None)
        if at is None:
            steps.append(data["step"])
        else:
            steps[at] = data["step"]
    elif name == "approval_pending":
        conversation["pending"] = data["pending"]
    elif name == "approval_decided":
        conversation["pending"] = None
    elif name == "answer":
        turns[-1]["answer"] = data["text"]
    elif name == "turn_ended" and data.get("message") and turns:
        turns[-1]["stopped"] = data["message"]


@dataclass
class ThreadState:
    thread_id: str
    status: str = IDLE
    transcript: dict | None = None
    subscribers: set = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    callbacks: list | None = None  # one Langfuse handler per Conversation, made on its first web turn
    streaming: bool = False  # the running turn is in the driver (Stop may cancel it)
    stopping: bool = False  # Stop cancelled the running turn
    # Each failed or stopped turn's message by turn index, merged back whenever the transcript is
    # rebuilt from the checkpoint, for the server's lifetime. Never in the graph's messages: the
    # model must not see it.
    stopped: dict[int, str] = field(default_factory=dict)

    def publish(self, name: str, data: dict) -> None:
        apply_event(self.transcript, name, data)
        if name == "turn_ended" and data.get("message") and self.transcript["turns"]:
            self.stopped[len(self.transcript["turns"]) - 1] = data["message"]
        for queue in self.subscribers:
            queue.put_nowait((name, data))

    def snapshot(self) -> tuple[str, dict]:
        return "state", {"status": self.status, "transcript": self.transcript}


class Turns:
    def __init__(self, *, graph, tools, checkpoint_path: str, langfuse_connected: bool = False,
                 model=None, logins: Logins | None = None):
        self.graph = graph
        self.tools = tools
        self.model = model
        self.logins = logins or Logins()
        self.checkpoint_path = checkpoint_path
        self.langfuse_connected = langfuse_connected
        self.threads: dict[str, ThreadState] = {}

    def add_tools(self, tools: list) -> None:
        """Bind more tools for later turns: the graph is rebuilt on the same checkpointer."""
        self.tools = [*self.tools, *tools]
        self.graph = build_graph(self.graph.checkpointer, self.tools, self.model)

    def broadcast(self, name: str, data: dict) -> None:
        """An event about no one Conversation, put on every watching queue."""
        for thread in self.threads.values():
            for queue in thread.subscribers:
                queue.put_nowait((name, data))

    def _thread(self, thread_id: str) -> ThreadState:
        return self.threads.setdefault(thread_id, ThreadState(thread_id))

    async def _checkpoint_transcript(self, thread: ThreadState) -> tuple[dict, bool]:
        """The transcript as the checkpoint has it, with the messages of turns that failed or were
        stopped on this server, and whether an Approval waits."""
        state = await self.graph.aget_state(self._config(thread))
        rebuilt = transcript(thread.thread_id, state.values.get("messages", []), state.interrupts)
        for at, message in thread.stopped.items():
            if at < len(rebuilt["turns"]):
                rebuilt["turns"][at]["stopped"] = message
        return rebuilt, bool(state.interrupts)

    async def _reload(self, thread: ThreadState) -> None:
        """Rebuild the transcript and status from the checkpoint (the CLI may have moved it on)."""
        thread.transcript, waiting = await self._checkpoint_transcript(thread)
        thread.status = AWAITING_APPROVAL if waiting else IDLE

    async def transcript(self, thread_id: str) -> dict | None:
        """The thread's transcript as a reload shows it (GET /conversations/{id}); None if it has no turn."""
        rebuilt, _ = await self._checkpoint_transcript(self.threads.get(thread_id) or ThreadState(thread_id))
        return rebuilt if rebuilt["turns"] else None

    def _config(self, thread: ThreadState) -> dict:
        return {
            "callbacks": thread.callbacks or [],
            "configurable": {"thread_id": thread.thread_id},
            # As the CLI: settings.max_iterations bounds model calls; this is the backstop.
            "recursion_limit": max(settings.max_iterations * 5 + 10, 40),
        }

    async def exists(self, thread_id: str) -> bool:
        """The thread has a turn in the checkpoint or in this server."""
        if thread_id in self.threads:
            return True
        state = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        return bool(state.values.get("messages"))

    async def subscribe(self, thread_id: str) -> asyncio.Queue:
        """A queue of the thread's events, starting with its current ``state``."""
        thread = self._thread(thread_id)
        queue: asyncio.Queue = asyncio.Queue()
        async with thread.lock:
            if thread.status != RUNNING:
                await self._reload(thread)
            queue.put_nowait(thread.snapshot())
            thread.subscribers.add(queue)
        return queue

    def unsubscribe(self, thread_id: str, queue: asyncio.Queue) -> None:
        thread = self.threads.get(thread_id)
        if thread is not None:
            thread.subscribers.discard(queue)

    def _ensure_callbacks(self, thread: ThreadState) -> None:
        if thread.callbacks is None:
            # The CLI's rule: the trace id is the thread id without dashes (Langfuse wants 32 hex chars).
            thread.callbacks = ([get_callback_handler(trace_id=thread.thread_id.replace("-", ""))]
                                if self.langfuse_connected else [])

    async def ask(self, thread_id: str, question: str) -> None:
        """Start a turn on the thread with this question; refused while one runs."""
        thread = self._thread(thread_id)
        async with thread.lock:
            if thread.status == RUNNING:
                raise TurnRefused("A turn is already running in this Conversation.")
            await self._reload(thread)
            self._ensure_callbacks(thread)
            pending = thread.transcript["pending"]
            thread.status = RUNNING
            if pending is None:
                thread.publish("turn_started", {"question": question})
            else:
                # As in the CLI, the Follow-up rejects the pending Approval (the driver abandons it,
                # which ends the earlier turn); the Follow-up's own turn starts after that.
                thread.publish("approval_decided", {"interrupt_id": pending["interrupt_id"], "decision": "reject"})
            thread.task = asyncio.create_task(self._run(thread, question, abandoning=pending is not None))

    async def decide(self, thread_id: str, interrupt_id: str, decision: str) -> None:
        """Answer the thread's pending Approval ("approve" or "reject") and continue its turn.
        Refused unless the thread waits at the Approval with this interrupt id (a stale tab's
        decision must not resume a checkpoint that has moved on)."""
        thread = self._thread(thread_id)
        async with thread.lock:
            if thread.status == RUNNING:
                raise TurnRefused("A turn is already running in this Conversation.")
            await self._reload(thread)
            pending = thread.transcript["pending"]
            if pending is None or pending["interrupt_id"] != interrupt_id:
                raise TurnRefused("This Approval is no longer pending.")
            self._ensure_callbacks(thread)
            thread.status = RUNNING
            thread.publish("approval_decided", {"interrupt_id": interrupt_id, "decision": decision})
            thread.task = asyncio.create_task(self._run(thread, resume_decision=decision))

    def stop(self, thread_id: str) -> None:
        """Cancel the thread's running turn, as Ctrl-C does in the CLI; refused unless one runs."""
        thread = self.threads.get(thread_id)
        if thread is None or thread.task is None or not thread.streaming or thread.stopping:
            raise TurnRefused("No turn is running in this Conversation.")
        thread.stopping = True
        thread.task.cancel()

    async def _run(self, thread: ThreadState, question: str | None = None, *,
                   resume_decision: str | None = None, abandoning: bool = False) -> None:
        outcome, message, error = "answered", None, None
        thread.streaming = True
        try:
            await self.logins.refresh_for_turn()
            graph, tools = self.graph, self.tools  # this turn's, whatever later logins bind
            with propagate_attributes(user_id="waffi", trace_name="web-run",
                                      metadata={"prompt-version": settings.prompt_version}):
                async for chunk in stream_conversation(graph, self._config(thread), tools=tools,
                                                       user_message=question, resume_decision=resume_decision):
                    if APPROVAL_ABANDONED in chunk:
                        abandoning = False
                        thread.publish("turn_started", {"question": question})
                        continue
                    if abandoning:
                        # An Approval met while abandoning is rejected in turn: no card for it.
                        chunk = {node: update for node, update in chunk.items() if node != "__interrupt__"}
                    elif "__interrupt__" in chunk:
                        outcome = "approval"
                    self._publish_chunk(thread, chunk)
        except ClaudeCodeError as exc:
            # As the CLI: the error already says what to do (ADR-016).
            outcome, message, error = "failed", f"Stopped: {exc}", f"{type(exc).__name__}: {exc}"
        except GraphRecursionError as exc:
            outcome, message, error = "failed", STEP_LIMIT_STOPPED, f"{type(exc).__name__}: {exc}"
        except asyncio.CancelledError:
            if not thread.stopping:
                raise  # the server is shutting down, not a Stop
            asyncio.current_task().uncancel()
            # As Ctrl-C: tool calls the cancel left open are answered, so the thread takes the next question.
            await close_interrupted_turn(self.graph, self._config(thread))
            await self._publish_closed_steps(thread)
            await self._publish_unsaved_turn_dropped(thread)
            outcome, message = "cancelled", STOPPED_BY_OWNER
        except Exception as exc:
            logger.exception("Web turn failed on thread %s", thread.thread_id)
            outcome, message, error = "error", f"Error: {type(exc).__name__}: {exc}", f"{type(exc).__name__}: {exc}"
        finally:
            thread.streaming = False
        try:
            await write_run_log(self.checkpoint_path, thread.thread_id, error=error,
                                  questions=[question] if question else [])
        except Exception:
            logger.exception("Run log write failed on thread %s", thread.thread_id)
        thread.status = AWAITING_APPROVAL if outcome == "approval" else IDLE
        thread.task = None
        thread.stopping = False
        thread.publish("turn_ended", {"status": thread.status, "outcome": outcome, "message": message})

    async def _publish_closed_steps(self, thread: ThreadState) -> None:
        """A step_finished for each running step of the last turn that now has its result."""
        state = await self.graph.aget_state(self._config(thread))
        results = {m.tool_call_id: m for m in state.values.get("messages", []) if isinstance(m, ToolMessage)}
        if not thread.transcript["turns"]:
            return
        for step in list(thread.transcript["turns"][-1]["steps"]):
            if step["result"] is None and step["id"] in results:
                thread.publish("step_finished", {"step": tool_step(step, results[step["id"]])})

    async def _publish_unsaved_turn_dropped(self, thread: ThreadState) -> None:
        """After a Stop that came before the turn's question reached the thread, a ``state`` with
        the transcript as a reload shows it, so the stop lands on the turn the thread ends with."""
        rebuilt, _ = await self._checkpoint_transcript(thread)
        if len(rebuilt["turns"]) != len(thread.transcript["turns"]):
            thread.publish("state", {"status": thread.status, "transcript": rebuilt})

    def _publish_chunk(self, thread: ThreadState, chunk: dict) -> None:
        for node, update in chunk.items():
            if node == "__interrupt__":
                thread.publish("approval_pending", {"pending": pending_approval(update)})
                continue
            if not isinstance(update, dict):
                continue
            for message in update.get("messages", []):
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        thread.publish("step_started", {"step": tool_step(call, None)})
                    if not message.tool_calls:
                        thread.publish("answer", {"text": message_text(message.content)})
                elif isinstance(message, ToolMessage):
                    known = next((s for s in thread.transcript["turns"][-1]["steps"]
                                  if s["id"] == message.tool_call_id), None)
                    call = {"id": message.tool_call_id, "name": known["name"] if known else message.name,
                            "args": known["args"] if known else {}}
                    thread.publish("step_finished", {"step": tool_step(call, message)})
