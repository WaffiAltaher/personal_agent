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

from typing import Annotated

from googleapiclient.errors import HttpError
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy
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
    Tool call present → go to tools. Final answer → END.
    This is the hinge of the ReAct loop.
    """
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


# ---------------------------------------------------------------------------
# 6. Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    """
    Wire nodes and edges into a compiled graph.

    The tools node uses tools_with_fallback as its function (catches
    exhausted-retry exceptions) and gets TOOL_RETRY_POLICY for automatic
    retries on transient failures. LangGraph applies the retry policy to
    whatever function is registered as the node, including wrappers.
    """
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
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
            "tools": "tools",
            END: END,
        },
    )

    graph.add_edge("tools", "agent")

    return graph.compile()


# Module-level compiled graph — import this from other modules
agent_graph = build_graph()
