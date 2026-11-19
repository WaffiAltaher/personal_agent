"""
conversations.py — the Conversation list and transcript of the web interface (ADR-018).

The list reads the checkpoint file directly: one row per thread, titled by its first question,
dated by its latest checkpoint. A transcript is rebuilt from a thread's state: ``transcript``
turns the messages and pending interrupts into the JSON shape the React app draws, and the live
events of ticket 04 reuse its pieces (``tool_step``, ``pending_approval``).
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

TITLE_LENGTH = 80
_SERDE = JsonPlusSerializer()


def message_text(content) -> str:
    """A message's content as plain text: a string, or the text blocks of a list."""
    if isinstance(content, str):
        return content
    return "".join(
        block if isinstance(block, str) else block.get("text", "")
        for block in content
        if isinstance(block, str) or block.get("type") == "text"
    )


def title_of(question: str) -> str:
    question = " ".join(question.split())
    return question if len(question) <= TITLE_LENGTH else question[:TITLE_LENGTH - 1] + "…"


def _checkpoint(row) -> dict:
    return _SERDE.loads_typed((row[0], row[1]))


def _first_question(messages) -> str | None:
    return next((message_text(m.content) for m in messages if isinstance(m, HumanMessage)), None)


def list_conversations(db_path: str) -> list[dict]:
    """Every thread of the checkpoint file that holds a question, newest activity first.
    ``updated_at`` is the epoch seconds of the thread's latest checkpoint."""
    if not Path(db_path).exists():
        return []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        latest = connection.execute(
            "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints WHERE checkpoint_ns = '' GROUP BY thread_id"
        ).fetchall()
        rows = []
        for thread_id, latest_id in latest:
            # The first question is in an early checkpoint, which is small: no need to load the latest for it.
            title = None
            for early in connection.execute(
                    "SELECT type, checkpoint FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = '' "
                    "ORDER BY checkpoint_id LIMIT 3", (thread_id,)):
                title = _first_question(_checkpoint(early)["channel_values"].get("messages", []))
                if title is not None:
                    break
            if title is None:
                continue
            last = connection.execute(
                "SELECT type, checkpoint FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = '' "
                "AND checkpoint_id = ?", (thread_id, latest_id)).fetchone()
            rows.append({
                "thread_id": thread_id,
                "title": title_of(title),
                "updated_at": datetime.fromisoformat(_checkpoint(last)["ts"]).timestamp(),
            })
    finally:
        connection.close()
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return rows


def tool_step(call: dict, result: ToolMessage | None) -> dict:
    """One tool call of a turn: its arguments and, once it has run, its result."""
    return {
        "id": call["id"],
        "name": call["name"],
        "args": call["args"],
        "result": None if result is None else message_text(result.content),
        "error": result is not None and result.status == "error",
    }


def pending_approval(interrupts) -> dict | None:
    """The Approval a thread waits at: the CLI's message and actions, plus the interrupt's id."""
    if not interrupts:
        return None
    interrupt = interrupts[0]
    return {"interrupt_id": interrupt.id, **interrupt.value}


def transcript(thread_id: str, messages, interrupts) -> dict:
    """``{thread_id, turns, pending}``. A turn is one question with its tool steps and its answer
    (None until there is one)."""
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    turns: list[dict] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append({"question": message_text(message.content), "steps": [], "answer": None})
        elif isinstance(message, AIMessage) and turns:
            turns[-1]["steps"] += [tool_step(call, results.get(call["id"])) for call in message.tool_calls]
            if not message.tool_calls:
                turns[-1]["answer"] = message_text(message.content)
    return {"thread_id": thread_id, "turns": turns, "pending": pending_approval(interrupts)}
