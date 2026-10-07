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
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, SystemMessage, ToolMessage
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
from agent.memory import ContextBudgetManager, RunRecord, TokenCounter, get_episodic_memory, get_semantic_memory
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
# on each node return, it *appends* the new messages to the existing list.
# This is what gives the agent its memory within a single run.

class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    token_usage_estimate: dict | None  # set by check_context_budget each iteration
    errors: Annotated[list[dict], operator.add]


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
            return await execute(request)
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


def build_runtime_context() -> str:
    """Return runtime facts the model needs but cannot infer reliably."""
    now = datetime.now(LOCAL_TIMEZONE)
    return (
        f"Current date/time: {now.isoformat()}\n"
        "Timezone: Europe/Amsterdam\n"
        "When the user asks for relative dates like today, this week, or next 7 days, "
        "compute explicit ISO 8601 startDateTime and endDateTime values before calling calendar tools. "
        "When presenting calendar results, convert tool timestamps to Europe/Amsterdam "
        "unless the user explicitly asks for another timezone."
    )

def check_context_budget(state: AgentState) -> dict:
    """Monitor context window usage before each LLM call.

    - Logs a DEBUG budget report every iteration (zero overhead in normal operation).
    - Logs a WARNING if the warning threshold is exceeded.
    - If the hard limit is exceeded, removes old messages from state via RemoveMessage
      so the LLM never receives a context that would cause an API error.
    - Always writes token_usage_estimate into state for downstream inspection.
    The node itself is visible in Langfuse as a span — no separate event needed.
    """
    counter = TokenCounter()
    counts = counter.count_messages(state.get("messages", []))
    report = counter.build_budget_report(state.get("messages", []), [])
    total = counts["total"]

    if total > settings.context_hard_limit:
        logger.warning(
            "Context hard limit exceeded (%d tokens). Trimming messages.\n%s",
            total,
            report,
        )
        cbm = ContextBudgetManager()
        trimmed = cbm.trim_messages(state.get("messages", []), settings.context_hard_limit)
        kept_ids = {m.id for m in trimmed if getattr(m, "id", None)}
        to_remove = [
            RemoveMessage(id=m.id)
            for m in state.get("messages", [])
            if getattr(m, "id", None) and m.id not in kept_ids
        ]
        update: dict = {"token_usage_estimate": counts}
        if to_remove:
            update["messages"] = to_remove
        return update
    elif total > settings.context_warning_threshold:
        logger.warning("Context warning threshold exceeded (%d tokens).\n%s", total, report)
    else:
        logger.debug("Context budget check:\n%s", report)

    return {"token_usage_estimate": counts}


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
    On 'reject':  injects a ToolMessage for each pending tool call so the
                  message history stays well-formed, then routes back to
                  agent so the LLM can acknowledge the cancellation.

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

    # Rejected — inject a ToolMessage for every pending tool call so the
    # message history stays well-formed, then route back to agent.
    rejection_messages = [
        ToolMessage(
            content=(
                f"Action '{tc['name']}' was rejected by the user. "
                "Do not retry this action. Acknowledge the cancellation."
            ),
            tool_call_id=tc["id"],
        )
        for tc in tool_calls  # ALL tool calls, not just those needing approval
    ]
    return Command(goto="agent", update={"messages": rejection_messages})


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

def build_graph(checkpointer=None, tools: list[BaseTool] | None = None, model: BaseChatModel | None = None):
    """
    Wire nodes and edges into a compiled graph.

    Pass a checkpointer (from get_checkpointer()) to enable HITL interrupts
    and persistent state. Without a checkpointer, interrupt() still pauses,
    but resuming with Command(resume=...) raises RuntimeError: nothing was saved.

    Pass a chat model to use it instead of the one configured in settings
    (tests and the eval harness inject a scripted fake model this way).

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
    llm = model.bind_tools(tools)

    # ToolNode handles the mechanical work of tool execution:
    # - reads the AIMessage's tool_calls field
    # - invokes the matching tool with the provided args
    # - wraps the result in a ToolMessage (which the LLM reads on the next step)
    # - handles parallel tool calls if the LLM calls multiple tools at once
    # awrap_tool_call wraps each individual call with retry + error handling.
    tool_node = ToolNode(tools, awrap_tool_call=retry_tool_call)

    async def agent_node(state: AgentState) -> dict:
        """
        The reasoning node. Calls the LLM with the current message history.
        Returns a dict with a `messages` key. The add_messages reducer appends
        it to state rather than overwriting.
        """
        messages = [
            SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{build_runtime_context()}")
        ] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

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
            return await tool_node.ainvoke(state)
        except GraphBubbleUp:
            raise  # interrupt() from a tool must pause the graph, not become an error
        except Exception as exc:
            last_message = state["messages"][-1]
            tool_calls = getattr(last_message, "tool_calls", [])

            logger.exception(
                "Tool node failed unexpectedly",
                extra={
                    "tool_calls": tool_calls,
                    "exception_type": type(exc).__name__,
                },
            )

            if not tool_calls:
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
                        "Please let the user know this tool is temporarily unavailable "
                        "and suggest they try again later or use an alternative approach."
                    ),
                    tool_call_id=tc["id"],
                )
                for tc in tool_calls
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
                for tc in tool_calls
            ]
            return {"messages": error_messages, "errors": error_records}

    graph = StateGraph(AgentState)

    graph.add_node("check_context_budget", check_context_budget)
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

def log_run_to_memory(result: dict, user_input: str) -> None:
    """
    Extract run data from a completed graph result dict and persist it to both
    episodic memory (SQLite) and semantic memory (Chroma interactions).

    Call this after agent_graph.invoke() returns (outside any interrupt loop).
    Failures are silently caught so memory issues never break the main flow.
    """
    try:
        messages: list[BaseMessage] = result.get("messages", [])

        # Final answer: last AIMessage without pending tool calls
        final_output = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                if isinstance(msg.content, str):
                    final_output = msg.content
                elif isinstance(msg.content, list):
                    final_output = " ".join(
                        block["text"]
                        for block in msg.content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                break

        # All tool names called during the run
        tools_called: list[str] = [
            tc["name"]
            for msg in messages
            if isinstance(msg, AIMessage)
            for tc in getattr(msg, "tool_calls", [])
        ]

        # Token usage from the last AI message that carries usage_metadata
        token_usage: dict | None = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                meta = getattr(msg, "usage_metadata", None)
                if meta:
                    token_usage = {
                        "prompt": meta.get("input_tokens", 0),
                        "completion": meta.get("output_tokens", 0),
                        "total": meta.get("total_tokens", 0),
                    }
                    break

        run = RunRecord(
            user_input=user_input,
            final_output=final_output,
            tools_called=tools_called,
            token_usage=token_usage,
            success=True,
        )

        run_id = get_episodic_memory().log_run(run)

        if final_output:
            get_semantic_memory().ingest_interaction(user_input, final_output, run_id)

    except Exception:
        # Memory failures must not crash the agent
        pass
