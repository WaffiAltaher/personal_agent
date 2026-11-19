"""Shared entry point for starting and resuming agent conversations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from agent.graph import answered_tool_call_ids, latest_ai_tool_batch, new_runtime_clock_iso

MOVED_ON_REJECTION = (
    "The owner moved on without approving. Do not retry this action. Acknowledge and continue."
)

INTERRUPTED_BY_OWNER = (
    "Interrupted by the owner (Ctrl-C) before this finished; its outcome is unknown. "
    "Do not retry it unless the owner asks."
)

# stream_conversation's marker between abandoning a pending Approval and the new turn.
APPROVAL_ABANDONED = "__approval_abandoned__"
_TURN_INPUT = "__turn_input__"


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


async def close_interrupted_turn(graph, config) -> None:
    """After a turn was cancelled mid-graph, answer each open tool call "interrupted by the owner"
    so the thread never holds an unanswered tool call. A pending Approval is left as it is:
    the next user message abandons it (run_conversation). Safe to run again: calls already
    answered are left alone, so it also runs before each new user message, in case an earlier
    run of it was itself interrupted before its write."""
    state = await graph.aget_state(config)
    if state.interrupts:
        return
    messages = state.values.get("messages", [])
    last_ai = latest_ai_tool_batch(messages)
    if last_ai is None:
        return
    answered = answered_tool_call_ids(messages)
    closing = [
        ToolMessage(content=INTERRUPTED_BY_OWNER, tool_call_id=tc["id"], name=tc["name"], status="error")
        for tc in last_ai.tool_calls
        if tc["id"] not in answered
    ]
    if closing:
        # As human_review: it routes by Command, so the update leaves no next step pending.
        await graph.aupdate_state(config, {"messages": closing}, as_node="human_review")


async def _turn_steps(
    graph,
    config,
    *,
    user_message: str | None,
    resume_decision: str | None,
    today: date | None,
) -> AsyncIterator[dict]:
    """Apply the turn rules (refusals, closing a cancelled turn, abandoning a pending Approval):
    yields each node update of abandoning a pending Approval, then ``{_TURN_INPUT: input}``, the
    graph input that runs the turn."""
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
        yield {_TURN_INPUT: Command(resume=resume_decision)}
        return

    assert user_message is not None
    await close_interrupted_turn(graph, config)
    # Acknowledging the rejection may park at another Approval: that one is abandoned too.
    interrupted = pending
    while interrupted:
        interrupted = False
        async for chunk in graph.astream(_abandon_resume_command(), config=config, stream_mode="updates"):
            interrupted = interrupted or "__interrupt__" in chunk
            yield chunk
    yield {_TURN_INPUT: {
        "messages": [HumanMessage(content=user_message)],
        "model_call_count": 0,
        "runtime_clock_iso": new_runtime_clock_iso(today),
        "last_model_input_tokens": None,
        "message_count_at_last_model_call": 0,
        "stubbed_tool_call_ids": [],
    }}


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
    async for step in _turn_steps(graph, config, user_message=user_message, resume_decision=resume_decision,
                                  today=today):
        turn = step.get(_TURN_INPUT)
    return await graph.ainvoke(turn, config=config)


async def stream_conversation(
    graph,
    config,
    *,
    tools: list[BaseTool],
    user_message: str | None = None,
    resume_decision: str | None = None,
    today: date | None = None,
) -> AsyncIterator[dict]:
    """run_conversation's streaming form, under the same rules: yields each node's update as it
    happens (``{node: update}``, or ``{"__interrupt__": (Interrupt, ...)}`` when the turn parks at
    an Approval). The turn's final state is the thread's, as after run_conversation.

    A user message sent while an Approval waits first abandons it: those updates come first (the
    rejected Write actions, and the agent's acknowledgement, which belong to the earlier turn), then
    ``{APPROVAL_ABANDONED: True}``, then the new turn's updates."""
    abandoned = False
    async for step in _turn_steps(graph, config, user_message=user_message, resume_decision=resume_decision,
                                  today=today):
        if _TURN_INPUT in step:
            turn = step[_TURN_INPUT]
        else:
            abandoned = True
            yield step
    if abandoned:
        yield {APPROVAL_ABANDONED: True}
    async for chunk in graph.astream(turn, config=config, stream_mode="updates"):
        yield chunk
