# src/agent/tools/memory.py
"""Memory retrieval tools — semantic and episodic."""

from langchain_core.tools import tool

from agent.config import settings
from agent.memory import get_episodic_memory, get_semantic_memory
from agent.tools.classification import write_action


@write_action
@tool
def remember(fact: str) -> str:
    """
    Store an explicit fact in long-term semantic memory after owner approval.

    Use when the owner asks you to remember something for future sessions.
    Do not call this unless they want the fact persisted.
    """
    memory_id = get_semantic_memory().remember(fact)
    return f"Stored memory {memory_id}."


@tool
def retrieve_memory(query: str) -> str:
    """
    Search approved memories and ingested documents for context relevant
    to the query. Returns the top matches with source and relevance score.
    Write the search query yourself from the user's request.
    Use this when the user references something they may have asked before,
    or when background context from prior sessions could improve the answer.
    """
    chunks = get_semantic_memory().search_all(query, k=settings.memory_top_k)

    if not chunks:
        return "No relevant memory found."

    parts = [
        f"[{i}] source={chunk.source}, score={chunk.score:.2f}\n{chunk.content}"
        for i, chunk in enumerate(chunks, 1)
    ]
    return "\n\n".join(parts)


@tool
def retrieve_episodic_memory(
    terms: str = "",
    since: str | None = None,
    until: str | None = None,
    recent: int = 5,
) -> str:
    """
    Look up past agent runs from episodic memory.

    When `terms` is non-empty, searches run history with SQLite full-text search
    (whole words, ranked by relevance), optionally limited to runs between `since`
    and `until` (ISO dates or timestamps). Write the search terms and date range
    yourself from the user's question. When `terms` is empty, returns the
    `recent` most recent runs instead.

    Use this when the user asks things like:
    - "what did I ask you yesterday?"
    - "find runs where I asked about email"
    - "show me my last 3 sessions"
    - "did you successfully draft an email last time?"
    """
    mem = get_episodic_memory()

    if terms.strip():
        runs = mem.search_runs(terms, n=recent, since=since, until=until)
        header = f'Runs matching "{terms.strip()}"'
    else:
        runs = mem.get_recent_runs(n=recent)
        header = f"Last {recent} runs"

    if not runs:
        return "No matching runs found in episodic memory."

    parts = [header]
    for i, run in enumerate(runs, 1):
        tools = ", ".join(run.tools_called) if run.tools_called else "none"
        status = run.outcome
        tokens = (
            f"{run.token_usage['total']} tokens" if run.token_usage else "n/a"
        )
        parts.append(
            f"\n[{i}] {status} {run.timestamp[:19].replace('T', ' ')} | tools: {tools} | {tokens}"
            f"\n    Q: {run.user_input}"
            f"\n    A: {run.final_output[:200]}{'…' if len(run.final_output) > 200 else ''}"
        )

    return "\n".join(parts)
