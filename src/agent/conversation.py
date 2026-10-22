"""Shared entry point for starting and resuming agent conversations."""

from __future__ import annotations

from datetime import date

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from agent.graph import new_runtime_clock_iso

MOVED_ON_REJECTION = (
    "The owner moved on without approving. Do not retry this action. Acknowledge and continue."
)


class ConversationDriverError(ValueError):
    """Invalid resume or conversation input (refused, not crashed)."""


async def has_pending_approval(graph, config) -> bool:
    state = await graph.aget_state(config)
    return bool(state.interrupts)


def _abandon_resume_command() -> Command:
    return Command(resume={"kind": "reject_writes", "reason": MOVED_ON_REJECTION})


async def _abandon_pending_approval(graph, config) -> None:
    """Reject pending Write actions so reads can finish before a new user message."""
    await graph.ainvoke(_abandon_resume_command(), config=config)


async def run_conversation(
    graph,
    config,
    *,
    tools: list[BaseTool],
    user_message: str | None = None,
    resume_decision: str | None = None,
    today: date | None = None,
) -> dict:
    """Start or continue a conversation. Exactly one of user_message or resume_decision."""
    if (user_message is None) == (resume_decision is None):
        raise ConversationDriverError("Pass exactly one of user_message or resume_decision.")

    pending = await has_pending_approval(graph, config)

    if resume_decision is not None:
        if not str(resume_decision).strip():
            raise ConversationDriverError("Resume requires a decision; an empty decision is refused.")
        if not pending:
            raise ConversationDriverError(
                "This conversation has no pending approval; resume is refused."
            )
        return await graph.ainvoke(Command(resume=resume_decision), config=config)

    assert user_message is not None
    if pending:
        await _abandon_pending_approval(graph, config)
    return await graph.ainvoke(
        {
            "messages": [HumanMessage(content=user_message)],
            "model_call_count": 0,
            "runtime_clock_iso": new_runtime_clock_iso(today),
            "last_model_input_tokens": None,
            "message_count_at_last_model_call": 0,
        },
        config=config,
    )
