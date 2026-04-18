# src/agent/graph.py
"""
graph.py — The core ReAct agent graph.

Graph topology:
  agent → [should_continue] → tools → agent  (ReAct loop)
                            ↘ END             (final answer)

Error handling strategy — two distinct mechanisms:

  1. RetryPolicy on the tools node:
     Handles uncaught exceptions (network blips, unexpected crashes).
     LangGraph automatically re-executes the tools node up to max_attempts
     times with exponential backoff before giving up.
     Only retries on genuinely transient errors:
       - ConnectionError / TimeoutError: network-level blips
       - HttpError 429 or 5xx: rate limits and server-side failures
     Does NOT retry on:
       - HttpError 4xx (except 429): auth/not-found — retrying won't help
       - ValueError / TypeError: bad args — the LLM should fix these

  2. Tool-level error strings (already in place in each tool):
     Each tool catches its own exceptions and returns "Error: ..." strings.
     ToolNode wraps these in ToolMessages. The LLM sees them on the next
     reasoning step and can adapt — try different args, a different tool,
     or explain the failure to the user. This handles semantic failures
     where the tool ran fine from Python's perspective but the result was bad.

  Fallback wrapper (tools_with_fallback):
     When RetryPolicy exhausts all attempts it re-raises the final exception.
     Without a wrapper this crashes the graph. tools_with_fallback catches
     that exception and injects a ToolMessage per attempted tool call so the
     message history stays well-formed and the LLM can respond gracefully.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

from googleapiclient.errors import HttpError
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, RetryPolicy, interrupt
from typing_extensions import TypedDict

from agent.config import settings
from agent.tools import ALL_TOOLS


# ---------------------------------------------------------------------------
# 1. State
# ---------------------------------------------------------------------------
# State is the only thing that flows through the graph.
# Every node receives it, every node returns a partial update to it.
#
# `add_messages` is a reducer: instead of overwriting the messages list
# on each node return, it *appends* the new messages to the existing list.
# This is what gives the agent its memory within a single run.

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# 2. Tools and LLM
# ---------------------------------------------------------------------------

TOOLS = ALL_TOOLS

# bind_tools serialises Pydantic schemas and docstrings into the JSON format
# the model API expects, so Gemini knows what tools it can call and how.
llm = ChatGoogleGenerativeAI(
    model=settings.model_name,
    google_api_key=settings.google_api_key,
).bind_tools(TOOLS)

# ToolNode handles the mechanical work of tool execution:
# - reads the AIMessage's tool_calls field
# - invokes the matching tool with the provided args
# - wraps the result in a ToolMessage (which the LLM reads on the next step)
# - handles parallel tool calls if the LLM calls multiple tools at once
tool_node = ToolNode(TOOLS)

# Tools that require explicit human approval before execution.
# Read-only tools are NOT listed here — they pass through silently.
# Add write tools here as they are implemented.
TOOLS_REQUIRING_APPROVAL: set[str] = {
    "create_draft_email",    # saves a draft to Gmail
    "send_email",            # future — sends immediately, irreversible
    "create_calendar_event", # future — creates a calendar event
    "delete_file",           # future — destructive filesystem operation
}


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
    if isinstance(exc, HttpError):
        # 429 Too Many Requests and 5xx server errors are transient.
        # 4xx (except 429) are permanent — wrong credentials, not found, etc.
        return exc.status_code == 429 or exc.status_code >= 500
    return False


# Backoff sequence with jitter (approximate):
#   attempt 1 → immediately
#   attempt 2 → wait ~1s
#   attempt 3 → wait ~2s
#   → give up, re-raise exception (caught by tools_with_fallback)
TOOL_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    initial_interval=1.0,
    backoff_factor=2.0,
    jitter=True,
    retry_on=_should_retry,
)


# ---------------------------------------------------------------------------
# 4. Nodes
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful personal data agent.

You have access to a set of tools for interacting with the user's local
environment and external data sources. Each tool's name, description, and
argument schema are provided separately by the runtime — rely on those
descriptions to decide which tool fits a given step, rather than guessing
from the tool name alone.

Operating guidelines:
- Reason step by step before acting. State briefly what you plan to do and
  why, then call the tool.
- Prefer calling a tool over speculating whenever the answer depends on the
  contents of a file, the structure of a directory, or current information
  you cannot reliably know from memory.
- If you are unsure whether a path exists or what it contains, explore
  before you read — don't guess file paths.
- Tools return plain strings. If a result starts with "Error:", read it
  carefully and adapt your next step; do not retry the exact same call.
- Stop once you have enough information to answer. Do not chain tool calls
  beyond what the question requires.
- When you answer, be concise and cite which files or sources the answer
  came from.
"""


def agent_node(state: AgentState) -> dict:
    """
    The reasoning node. Calls the LLM with the current message history.
    Returns a dict with a `messages` key. The add_messages reducer appends
    it to state rather than overwriting.
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def human_review_node(state: AgentState) -> Command[Literal["tools", "agent"]]:
    """
    Human-in-the-loop gate between agent and tools.

    Inspects pending tool calls on the last AIMessage.
    - If none require approval → proceeds to tools automatically (no interrupt).
    - If any require approval → calls interrupt() to pause the graph.

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
        if tc["name"] in TOOLS_REQUIRING_APPROVAL
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
    # interrupt() raises internally; execution resumes from this exact point
    # when Command(resume=...) is passed with the same thread_id.
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


def tools_with_fallback(state: AgentState) -> dict:
    """
    Wrapper around ToolNode that catches exhausted-retry exceptions.

    When RetryPolicy gives up it re-raises the final exception. Without this
    wrapper the graph crashes. With it, we catch the exception and return a
    ToolMessage per attempted tool call so the message history stays
    well-formed and the LLM can give the user a graceful response.

    Why a wrapper rather than a separate fallback node?
    Because we need the tool_calls from the last AIMessage to construct
    properly-formed ToolMessages (each must reference the correct
    tool_call_id). The LLM requires a ToolMessage for every tool_call_id
    it produced — missing ones cause a malformed message history error on
    the next LLM invocation.
    """
    try:
        return tool_node.invoke(state)
    except Exception as exc:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", [])

        if not tool_calls:
            # Shouldn't happen, but handle it gracefully
            return {"messages": []}

        error_messages = [
            ToolMessage(
                content=(
                    f"Tool '{tc['name']}' failed after all retry attempts. "
                    f"Error: {type(exc).__name__}: {exc}. "
                    "Please let the user know this tool is temporarily unavailable "
                    "and suggest they try again later or use an alternative approach."
                ),
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
        return {"messages": error_messages}


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

_CHECKPOINT_DIR = Path(__file__).resolve().parents[3] / "checkpoints"
_CHECKPOINT_DIR.mkdir(exist_ok=True)
CHECKPOINT_DB = str(_CHECKPOINT_DIR / "hitl.db")


@contextmanager
def get_checkpointer():
    """
    Context manager that opens a SqliteSaver, yields it, then closes the
    underlying sqlite3 connection when the caller's `with` block exits.

    Usage:
        with get_checkpointer() as checkpointer:
            graph = build_graph(checkpointer)
            graph.invoke(...)
    """
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Graph assembly
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None):
    """
    Wire nodes and edges into a compiled graph.

    Pass a checkpointer (from get_checkpointer()) to enable HITL interrupts
    and persistent state. Without a checkpointer, interrupt() will raise.

    Topology:
      agent → [should_continue] → human_review → [Command] → tools → agent
                                ↘ END                       ↘ agent (rejected)
    """
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node(
        "tools",
        tools_with_fallback,
        retry=TOOL_RETRY_POLICY,
    )

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "human_review": "human_review",
            END: END,
        },
    )

    # human_review routes itself via Command — no explicit edge needed from it
    # tools always loops back to agent
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)


# Module-level compiled graph for backwards compatibility (no checkpointer).
# Use build_graph(checkpointer) via get_checkpointer() when HITL is needed.
agent_graph = build_graph()
