# src/agent/graph.py
"""
graph.py — The core ReAct agent graph.

Graph topology:
  agent → [should_continue] → tools → agent  (ReAct loop)
                            ↘ END             (final answer)

Error handling strategy — two layers plus a safety net:

  1. Per-tool-call retry (retry_tool_call, plugged into ToolNode via awrap_tool_call):
     Handles exceptions raised by a single tool call (network blips, unexpected crashes).
     Only the failing call is re-executed, up to TOOL_RETRY_POLICY.max_attempts
     times with exponential backoff; siblings in a parallel batch are not re-run.
     Write actions (any tool not classified as read, see agent/tools/classification.py)
     are never retried, since a transient error on a write is ambiguous — it may
     have gone through.
     Only retries on genuinely transient errors:
       - ConnectionError / TimeoutError: network-level blips
       - HttpError 429 or 5xx: rate limits and server-side failures
       - TransientMcpError: an MCP server that closed the connection mid-call,
         or a tool error its server config marks transient (agent/tools/mcp_loader.py)
     Does NOT retry on:
       - HttpError 4xx (except 429): auth/not-found — retrying won't help
       - ValueError / TypeError: bad args — the LLM should fix these
     A call that still fails becomes a ToolMessage with status="error" (saying
     whether the error was transient or permanent) plus a structured `errors`
     record, so nothing raises out of the tools node.

  2. Tool-level error strings (already in place in each tool):
     Each tool catches its own exceptions and returns "Error: ..." strings.
     ToolNode wraps these in ToolMessages. The LLM sees them on the next
     reasoning step and can adapt — try different args, a different tool,
     or explain the failure to the user. This handles semantic failures
     where the tool ran fine from Python's perspective but the result was bad.

  Fallback wrapper (tools_with_fallback):
     Last-resort safety net for anything that escapes retry_tool_call (e.g. a
     bug in ToolNode itself). Without a wrapper this crashes the graph.
     tools_with_fallback catches that exception and injects a ToolMessage per
     tool call so the message history stays well-formed and the LLM can
     respond gracefully.
"""

import asyncio
import logging
import operator
import random
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, RetryPolicy, interrupt
from typing_extensions import TypedDict

from agent.chat_model import create_chat_model
from agent.config import settings
from agent.model_binding import bind_agent_tools, system_message_for_model
from agent.memory import get_episodic_memory
from agent.memory.context_view import (
    build_model_view,
    cap_tool_result_content,
    estimate_context_tokens,
)
from agent.memory.run_log import build_run_record
from agent.tools import LOCAL_TOOLS
from agent.tools.classification import is_read
from agent.tools.mcp_loader import TransientMcpError
from agent.prompts import get_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. State
# ---------------------------------------------------------------------------
# State is the only thing that flows through the graph.
# Every node receives it, every node returns a partial update to it.
#
# `add_messages` is a reducer: instead of overwriting the messages list
# on each node return, it *merges* the returned messages into the list by ID.
# A message whose ID is already in the list replaces that message; any other
# message is appended. This is what gives the agent its memory within a single run.

class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    token_usage_estimate: dict | None  # set by check_context_budget each iteration
    errors: Annotated[list[dict], operator.add]
    model_call_count: int  # model calls this user turn; reset on a new user message, not on resume
    runtime_clock_iso: str | None  # Europe/Amsterdam instant for the system prompt; fixed for the run
    last_model_input_tokens: int | None  # reported input tokens from the previous model call
    message_count_at_last_model_call: int  # len(state messages) before the previous model call
    stubbed_tool_call_ids: list[str]  # tool results cleared in the model view; state stays full


STEP_LIMIT_ANSWER = (
    "Stopped: the agent hit its step limit without a final answer. "
    "Try a narrower question."
)


def is_step_limit_answer(message: BaseMessage | None) -> bool:
    return (
        isinstance(message, AIMessage)
        and not getattr(message, "tool_calls", None)
        and message.content == STEP_LIMIT_ANSWER
    )


# ---------------------------------------------------------------------------
# 2. Tools and LLM
# ---------------------------------------------------------------------------

# Which tools require explicit human approval before execution is no longer a
# hand-maintained list of names. Every tool is classified as read or Write action
# when tools are loaded (agent/tools/classification.py), and the graph fails
# closed: a tool call is read only if its bound tool is classified read. Anything
# else (a Write action, an unclassified tool, an unknown tool name) needs approval
# in human_review_node and is never auto-retried by retry_tool_call.


# ---------------------------------------------------------------------------
# 3. Retry policy
# ---------------------------------------------------------------------------

def _should_retry(exc: Exception) -> bool:
    """
    Return True only for errors that are genuinely transient — i.e. where
    waiting and retrying is likely to succeed.

    Permanent failures (bad auth, resource not found, invalid args) return
    False so we don't waste time retrying something that will never work.
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, TransientMcpError):
        # Mapped at the MCP boundary (agent/tools/mcp_loader.py): a server that
        # closed the connection, or a tool error its server config marks transient.
        return True
    if isinstance(exc, HttpError):
        # 429 Too Many Requests and 5xx server errors are transient.
        # 4xx (except 429) are permanent — wrong credentials, not found, etc.
        return exc.status_code == 429 or exc.status_code >= 500
    return False


# Backoff sequence with jitter (approximate):
#   attempt 1 → immediately
#   attempt 2 → wait ~1s
#   attempt 3 → wait ~2s
#   → give up, return an error ToolMessage (see retry_tool_call)
# Not attached to a node: retry_tool_call reads only the backoff numbers from it.
TOOL_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    initial_interval=1.0,
    backoff_factor=2.0,
    jitter=True,
    retry_on=_should_retry,
)


async def retry_tool_call(request, execute):
    """
    Per-tool-call retry, plugged into ToolNode via awrap_tool_call.

    Retries ONLY the failing call (siblings in a parallel batch are not re-run),
    only on transient errors, and never for write tools (a transient error on a
    write is ambiguous: it may have gone through). Final failures become an
    error ToolMessage plus a structured `errors` record, so nothing raises.
    """
    policy = TOOL_RETRY_POLICY
    tool_call = request.tool_call
    interval = policy.initial_interval
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await execute(request)
            if isinstance(result, ToolMessage):
                capped = cap_tool_result_content(result.content)
                if capped != result.content:
                    result = ToolMessage(
                        content=capped,
                        tool_call_id=result.tool_call_id,
                        name=result.name,
                        status=getattr(result, "status", None),
                    )
            return result
        except GraphBubbleUp:
            # interrupt() and other LangGraph control flow are exceptions too;
            # they must reach the runtime, not become an error ToolMessage.
            raise
        except Exception as exc:
            transient = policy.retry_on(exc)
            is_write = not is_read(request.tool)  # fails closed: unknown tool → write
            if transient and not is_write and attempt < policy.max_attempts:
                await asyncio.sleep(interval + (random.uniform(0, 1) if policy.jitter else 0))
                interval = min(interval * policy.backoff_factor, policy.max_interval)
                continue

            if not transient:
                advice = "This is a permanent error; retrying will not help. Explain the problem to the user."
            elif is_write:
                advice = ("This is a transient error on a write action, so it was not retried: "
                          "it may have gone through. Ask the user to check before trying again.")
            else:
                advice = "This is a transient error; suggest trying again later or an alternative approach."
            logger.warning("Tool call failed", exc_info=exc, extra={"tool": tool_call["name"], "attempts": attempt})
            return Command(update={
                "messages": [ToolMessage(
                    content=(f"Tool '{tool_call['name']}' failed ({'transient' if transient else 'permanent'}) "
                             f"after {attempt} attempt(s). Error: {type(exc).__name__}: {exc}. {advice}"),
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                    status="error",
                )],
                "errors": [{
                    "node": "tools",
                    "tool": tool_call["name"],
                    "tool_call_id": tool_call["id"],
                    "args": tool_call.get("args"),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }],
            })


# ---------------------------------------------------------------------------
# 4. Nodes
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = get_prompt(settings.prompt_version)
LOCAL_TIMEZONE = ZoneInfo("Europe/Amsterdam")


# The time of day the model is told on a pinned date (see build_graph's `today`).
PINNED_TIME_OF_DAY = time(9, 0)


def build_runtime_context(
    at: datetime | None = None,
    *,
    today: date | None = None,
) -> str:
    """Return runtime facts the model needs but cannot infer reliably.

    Pass `at` for the run's fixed clock. With `today` only (Fixture world before the
    clock is stored), the date is that day at 09:00 local time.
    """
    if at is not None:
        now = at
    elif today is None:
        now = datetime.now(LOCAL_TIMEZONE)
    else:
        now = datetime.combine(today, PINNED_TIME_OF_DAY, tzinfo=LOCAL_TIMEZONE)
    return (
        f"Current date/time: {now.isoformat()}\n"
        "Timezone: Europe/Amsterdam\n"
        "When the user asks for relative dates like today, this week, or next 7 days, "
        "compute explicit ISO 8601 startDateTime and endDateTime values before calling calendar tools. "
        "When presenting calendar results, convert tool timestamps to Europe/Amsterdam "
        "unless the user explicitly asks for another timezone."
    )


def new_runtime_clock_iso(today: date | None = None) -> str:
    """Read the clock once when a user turn starts."""
    if today is None:
        now = datetime.now(LOCAL_TIMEZONE)
    else:
        now = datetime.combine(today, PINNED_TIME_OF_DAY, tzinfo=LOCAL_TIMEZONE)
    return now.isoformat()


def _runtime_instant(state: AgentState, today: date | None) -> datetime:
    iso = state.get("runtime_clock_iso")
    if iso:
        return datetime.fromisoformat(iso)
    return datetime.fromisoformat(new_runtime_clock_iso(today))


def _system_text_for_state(state: AgentState, today: date | None) -> str:
    return f"{SYSTEM_PROMPT}\n\n{build_runtime_context(_runtime_instant(state, today))}"


def make_check_context_budget(bound_tools: list, today: date | None):
    def check_context_budget(state: AgentState) -> dict:
        return _check_context_budget(state, bound_tools, today)

    return check_context_budget


def _check_context_budget(state: AgentState, bound_tools: list, today: date | None) -> dict:
    """Estimate context size before each LLM call; never mutates message state."""
    system_text = _system_text_for_state(state, today)
    messages = state.get("messages", [])
    total = estimate_context_tokens(
        state_messages=messages,
        system_text=system_text,
        tools=bound_tools,
        last_model_input_tokens=state.get("last_model_input_tokens"),
        message_count_at_last_model_call=state.get("message_count_at_last_model_call", 0),
    )
    counts = {"total": total, "message_count": len(messages)}

    if total > settings.context_clear_threshold:
        logger.warning(
            "Context above clear threshold (%d tokens); tool results will be stubbed in the model view.",
            total,
        )
    else:
        logger.debug("Context estimate before model call: %d tokens", total)

    update: dict = {"token_usage_estimate": counts}
    if not state.get("runtime_clock_iso"):
        update["runtime_clock_iso"] = new_runtime_clock_iso(today)
    return update


def check_context_budget(state: AgentState) -> dict:
    """Default hook for tests; production graphs use make_check_context_budget(tools)."""
    return _check_context_budget(state, [], None)


def _answered_tool_call_ids(messages: list[BaseMessage]) -> set[str]:
    return {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}


def _latest_ai_tool_batch(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            return message
    return None


def pending_write_tool_calls(messages: list[BaseMessage], read_tool_names: frozenset[str]) -> list[dict]:
    """Write tool calls on the latest AIMessage that do not yet have a ToolMessage."""
    last_ai = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)),
        None,
    )
    if last_ai is None:
        return []
    answered = _answered_tool_call_ids(messages)
    return [
        tc for tc in last_ai.tool_calls
        if tc["name"] not in read_tool_names and tc["id"] not in answered
    ]


OWNER_REJECTED = (
    "The owner rejected this action. Do not retry this action. Acknowledge the cancellation."
)


def build_write_rejection_message(tool_call: dict, *, reason: str) -> ToolMessage:
    return ToolMessage(
        content=f"Action '{tool_call['name']}' was rejected by the user. {reason}",
        tool_call_id=tool_call["id"],
        name=tool_call["name"],
        status="error",
    )


def human_review_node(state: AgentState, read_tool_names: frozenset[str]) -> Command[Literal["tools", "agent"]]:
    """
    Human-in-the-loop gate between agent and tools.

    Inspects pending tool calls on the last AIMessage.
    - If all are read tools (names in read_tool_names) → proceeds to tools
      automatically (no interrupt).
    - If any is a Write action (anything not read, including an unknown tool
      name) → calls interrupt() to pause the graph.

    The interrupt payload is displayed by the CLI (or any frontend).
    When the user responds, the graph resumes with their decision.

    On 'approve': routes to tools, execution continues normally.
    On reject:    injects an error ToolMessage for each pending Write action,
                  runs reads in the tools stage, then routes to agent so the
                  LLM can acknowledge the cancellation.

    Why Command instead of a plain dict return?
    Command lets a node specify both a state update AND the next node to
    route to dynamically. This avoids a conditional edge whose logic would
    duplicate what is already in this node.
    """
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", [])

    # Identify which pending calls need approval
    calls_needing_approval = [
        tc for tc in tool_calls
        if tc["name"] not in read_tool_names
    ]

    if not calls_needing_approval:
        # All tools are read-only — proceed without interrupting
        return Command(goto="tools")

    # Build a human-readable summary of what is about to happen
    action_summary = "\n".join(
        f"  • {tc['name']}({tc['args']})"
        for tc in calls_needing_approval
    )

    # Pause here — the CLI displays this payload and prompts the user.
    # interrupt() raises GraphInterrupt; the runtime saves a checkpoint and
    # returns. On Command(resume=...) with the same thread_id this whole node
    # re-runs from the top and interrupt() returns the resume value, so code
    # above this line runs twice and must stay side-effect free.
    decision = interrupt({
        "message": "The agent wants to perform the following action(s):",
        "actions": action_summary,
        "instructions": "Type 'approve' to proceed or 'reject' to cancel.",
    })

    if decision == "approve":
        return Command(goto="tools")

    if isinstance(decision, dict) and decision.get("kind") == "reject_writes":
        reason = decision.get("reason") or OWNER_REJECTED
    else:
        reason = OWNER_REJECTED

    rejection_messages = [
        build_write_rejection_message(tc, reason=reason)
        for tc in pending_write_tool_calls(state["messages"], read_tool_names)
    ]
    return Command(goto="tools", update={"messages": rejection_messages})


# ---------------------------------------------------------------------------
# 5. Routing
# ---------------------------------------------------------------------------

def should_continue(state: AgentState) -> str:
    """
    Inspect the last message to decide what happens next.
    Tool call present → human_review (which routes to tools or back to agent).
    Final answer → END.
    This is the hinge of the ReAct loop.
    """
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "human_review"
    return END


# ---------------------------------------------------------------------------
# 6. Checkpointer
# ---------------------------------------------------------------------------
# SqliteSaver persists graph state to disk so interrupted runs survive
# process restarts. We expose a context manager so callers (CLI, tests)
# own the connection lifecycle explicitly.
#
# check_same_thread=False is required because LangGraph may access the
# connection from background threads during graph execution.
#
# Switching to PostgresSaver for production requires changing one line here.

_CHECKPOINT_DIR = Path(__file__).resolve().parents[2] / "checkpoints"
_CHECKPOINT_DIR.mkdir(exist_ok=True)
CHECKPOINT_DB = str(_CHECKPOINT_DIR / "hitl.db")


@asynccontextmanager
async def get_checkpointer():
    """
    Async context manager that opens an AsyncSqliteSaver, yields it, then
    closes the underlying sqlite connection when the caller's block exits.

    Usage:
        async with get_checkpointer() as checkpointer:
            graph = build_graph(checkpointer)
            await graph.ainvoke(...)
    """
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB) as checkpointer:
        yield checkpointer


# ---------------------------------------------------------------------------
# 7. Graph assembly
# ---------------------------------------------------------------------------

def build_graph(
    checkpointer=None,
    tools: list[BaseTool] | None = None,
    model: BaseChatModel | None = None,
    today: date | None = None,
):
    """
    Wire nodes and edges into a compiled graph.

    Pass a checkpointer (from get_checkpointer()) to enable HITL interrupts
    and persistent state. Without a checkpointer, interrupt() still pauses,
    but resuming with Command(resume=...) raises RuntimeError: nothing was saved.

    Pass a chat model to use it instead of the one configured in settings
    (tests and the eval harness inject a scripted fake model this way).

    Pass `today` to pin the date the model is told (runs against the Fixture world pass
    its date, fixture_world.clock.today()); without it the model is told the real date.

    Topology:
      budget → agent → [should_continue] → human_review → [Command] → tools → budget
                                         ↘ END                       ↘ agent (rejected)
    """

    tools = tools or LOCAL_TOOLS
    # Classification is read once, from the tools actually bound to the graph.
    read_tool_names = frozenset(t.name for t in tools if is_read(t))

    # bind_tools serialises Pydantic schemas and docstrings into the JSON format
    # the model API expects, so the model knows what tools it can call and how.
    if model is None:
        model = create_chat_model()  # provider:model from settings.model_name
    llm = bind_agent_tools(model, tools)

    # ToolNode handles the mechanical work of tool execution:
    # - reads the AIMessage's tool_calls field
    # - invokes the matching tool with the provided args
    # - wraps the result in a ToolMessage (which the LLM reads on the next step)
    # - handles parallel tool calls if the LLM calls multiple tools at once
    # awrap_tool_call wraps each individual call with retry + error handling.
    tool_node = ToolNode(tools, awrap_tool_call=retry_tool_call)

    max_iterations = settings.max_iterations

    async def agent_node(state: AgentState) -> dict:
        """
        The reasoning node. Calls the LLM with the current message history.
        Returns a dict with a `messages` key. The add_messages reducer merges
        it into state by message ID rather than overwriting the list.
        """
        count = state.get("model_call_count", 0)
        if count >= max_iterations:
            return {"messages": [AIMessage(content=STEP_LIMIT_ANSWER)]}

        messages_before_call = len(state["messages"])
        system_text = _system_text_for_state(state, today)
        system_msg = system_message_for_model(system_text, llm)
        view, stubbed_ids = build_model_view(
            state["messages"],
            system_text=system_text,
            tools=tools,
            last_model_input_tokens=state.get("last_model_input_tokens"),
            message_count_at_last_model_call=state.get("message_count_at_last_model_call", 0),
            system_message=system_msg,
            stubbed_tool_call_ids=set(state.get("stubbed_tool_call_ids") or []),
        )
        response = await llm.ainvoke(view)
        usage = getattr(response, "usage_metadata", None) or {}
        update: dict = {
            "messages": [response],
            "model_call_count": count + 1,
            # A model whose usage sums several calls (claude_code: re-ask) reports the final prompt size apart.
            "last_model_input_tokens": (getattr(response, "response_metadata", None) or {}).get(
                "prompt_input_tokens", usage.get("input_tokens")
            ),
            "message_count_at_last_model_call": messages_before_call,
            "stubbed_tool_call_ids": sorted(stubbed_ids),
        }
        if not state.get("runtime_clock_iso"):
            update["runtime_clock_iso"] = new_runtime_clock_iso(today)
        return update

    async def tools_with_fallback(state: AgentState) -> dict:
        """
        Wrapper around ToolNode that catches anything escaping retry_tool_call.

        Per-call failures are already handled by retry_tool_call, so this only
        fires on unexpected errors. Without this wrapper the graph crashes.
        With it, we catch the exception and return a ToolMessage per attempted
        tool call so the message history stays well-formed and the LLM can
        give the user a graceful response.

        Why a wrapper rather than a separate fallback node?
        Because we need the tool_calls from the last AIMessage to construct
        properly-formed ToolMessages (each must reference the correct
        tool_call_id). The LLM requires a ToolMessage for every tool_call_id
        it produced — missing ones cause a malformed message history error on
        the next LLM invocation.
        """
        try:
            last_batch = _latest_ai_tool_batch(state["messages"])
            if last_batch is None:
                return {}

            tool_calls = last_batch.tool_calls or []
            answered = _answered_tool_call_ids(state["messages"])
            pending = [tc for tc in tool_calls if tc["id"] not in answered]
            if not pending:
                return {}
            if len(pending) == len(tool_calls):
                return await tool_node.ainvoke(state)

            filtered_ai = AIMessage(
                content=last_batch.content,
                tool_calls=pending,
                id=getattr(last_batch, "id", None),
            )
            without_batch = [
                m for m in state["messages"] if m is not last_batch and getattr(m, "id", None) != getattr(last_batch, "id", None)
            ]
            filtered_state = {**state, "messages": without_batch + [filtered_ai]}
            return await tool_node.ainvoke(filtered_state)
        except GraphBubbleUp:
            raise  # interrupt() from a tool must pause the graph, not become an error
        except Exception as exc:
            last_batch = _latest_ai_tool_batch(state["messages"])
            tool_calls = (last_batch.tool_calls or []) if last_batch is not None else []
            answered = _answered_tool_call_ids(state["messages"])
            pending = [tc for tc in tool_calls if tc["id"] not in answered]

            logger.exception(
                "Tool node failed unexpectedly",
                extra={
                    "tool_calls": tool_calls,
                    "exception_type": type(exc).__name__,
                },
            )

            if not pending:
                # Shouldn't happen, but handle it gracefully
                return {
                    "messages": [],
                    "errors": [{
                        "node": "tools",
                        "tool": None,
                        "tool_call_id": None,
                        "args": None,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }],
                }

            error_messages = [
                ToolMessage(
                    content=(
                        f"Tool '{tc['name']}' failed unexpectedly. "
                        f"Error: {type(exc).__name__}: {exc}. "
                        "This was a crash in the tool layer, not a normal tool result, so the "
                        "outcome is unknown: do not treat it as a success, and tell the user what failed."
                    ),
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    status="error",
                )
                for tc in pending
            ]
            error_records = [
                {
                    "node": "tools",
                    "tool": tc["name"],
                    "tool_call_id": tc["id"],
                    "args": tc.get("args"),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
                for tc in pending
            ]
            return {"messages": error_messages, "errors": error_records}

    graph = StateGraph(AgentState)

    graph.add_node("check_context_budget", make_check_context_budget(tools, today))
    graph.add_node("agent", agent_node)
    def human_review(state: AgentState) -> Command[Literal["tools", "agent"]]:
        return human_review_node(state, read_tool_names)

    graph.add_node("human_review", human_review)
    # No node-level retry: retrying here would re-run every tool call in the
    # batch (duplicating writes). Retry happens per call in retry_tool_call.
    graph.add_node("tools", tools_with_fallback)

    graph.set_entry_point("check_context_budget")

    # Budget check always feeds into agent
    graph.add_edge("check_context_budget", "agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "human_review": "human_review",
            END: END,
        },
    )

    # human_review routes itself via Command — no explicit edge needed from it
    # tools loops back through budget check before each new LLM call
    graph.add_edge("tools", "check_context_budget")

    return graph.compile(checkpointer=checkpointer)


# No module-level compiled graph: building one at import would build the
# configured chat model as a side effect, so a missing API key would crash the
# import instead of giving the CLI's clear startup error.
# Use build_graph(checkpointer) via get_checkpointer() when HITL is needed.


# ---------------------------------------------------------------------------
# 8. Post-run memory logging
# ---------------------------------------------------------------------------

def log_run_to_memory(
    result: dict,
    user_input: str,
    *,
    model_name: str | None = None,
    run_date: date | None = None,
    error: str | None = None,
) -> None:
    """
    Persist an episodic run log entry from a completed (or failed) graph result.

    Call this after the conversation driver finishes (outside any interrupt loop).
    Write failures are logged and do not crash the caller.
    """
    try:
        from agent.config import settings as _settings

        run = build_run_record(
            result,
            user_input,
            model_name=model_name or _settings.model_name,
            run_date=run_date or date.today(),
            error=error,
        )
        get_episodic_memory().log_run(run)
    except Exception as exc:
        logger.warning("Failed to write run log: %s", exc)
