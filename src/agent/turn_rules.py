"""
turn_rules.py — what the CLI and the web server do the same way around every turn (ADR-018).

The run config of a Conversation's turns, its Langfuse trace id and trace attributes, the message
and run log error a known failure ends a turn with, and the Conversation's run log entry, rebuilt
from its thread after every turn.
"""

from langchain_core.messages import HumanMessage
from langfuse import propagate_attributes
from langgraph.errors import GraphRecursionError

from agent.claude_code_model import ClaudeCodeError
from agent.config import settings
from agent.graph import get_checkpointer, log_run_to_memory

OWNER_USER_ID = "waffi"  # the Langfuse user id of every Conversation: the app has one owner

STEP_LIMIT_STOPPED = ("Stopped: the agent hit its step limit (~10 tool rounds) without a final answer. "
                      "Try a narrower question.")

# Failures that end the turn, not the session or the server: they are raised before a node writes
# anything, so the thread still ends on answered messages.
KNOWN_FAILURES = (ClaudeCodeError, GraphRecursionError)


def error_text(exc: BaseException) -> str:
    """A failure as its run log entry records it."""
    return f"{type(exc).__name__}: {exc}"


def known_failure(exc: ClaudeCodeError | GraphRecursionError) -> tuple[str, str]:
    """What the owner is shown for a known failure, and the error its run log entry records."""
    if isinstance(exc, ClaudeCodeError):
        # A Claude Code call that couldn't produce a turn already says what to do (ADR-016).
        return f"Stopped: {exc}", error_text(exc)
    return STEP_LIMIT_STOPPED, error_text(exc)


def trace_id(thread_id: str) -> str:
    """The Conversation's Langfuse trace id. Langfuse v4 (OTel-based) requires 32 lowercase hex
    chars, no dashes: it is derived from the thread id so the two IDs stay linked."""
    return thread_id.replace("-", "")


def run_config(thread_id: str, callbacks: list) -> dict:
    """The graph config of every turn in the Conversation."""
    return {
        "callbacks": callbacks,
        "configurable": {"thread_id": thread_id},
        # Backstop only: settings.max_iterations bounds model calls; keep headroom above that.
        "recursion_limit": max(settings.max_iterations * 5 + 10, 40),
    }


def trace_attributes(trace_name: str):
    """The attributes every span of a front end's turns carries (a context manager)."""
    return propagate_attributes(
        user_id=OWNER_USER_ID,
        trace_name=trace_name,
        metadata={"prompt-version": settings.prompt_version},
    )


def stringify_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


async def _conversation_so_far(db_path: str, config: dict) -> dict:
    """The Conversation's thread as last checkpointed, for its run log entry. No messages if it
    can't be read: the error that ended the session is the one to show."""
    try:
        async with get_checkpointer(db_path) as checkpointer:
            saved = await checkpointer.aget_tuple(config)
        return {"messages": [], **(saved.checkpoint["channel_values"] if saved else {})}
    except Exception:
        return {"messages": []}


async def write_run_log(db_path: str, thread_id: str, *, error: str | None = None,
                        questions: list[str] = ()) -> None:
    """Write the Conversation's run log entry from its thread in the checkpoint file at ``db_path``,
    replacing the thread's earlier entry. The questions are the thread's HumanMessages; ``questions``
    stands in only while the thread has none (a first turn that failed before checkpointing). ``error``
    is a failure not yet in the entry: the entry keeps the ones it already holds. Writes nothing for a
    thread with no question and no error."""
    result = await _conversation_so_far(db_path, {"configurable": {"thread_id": thread_id}})
    asked = [stringify_content(m.content) for m in result["messages"] if isinstance(m, HumanMessage)]
    asked = asked or list(questions)
    if not asked and not error:
        return
    log_run_to_memory(result, "\n".join(asked), model_name=settings.model_name, error=error, thread_id=thread_id)
