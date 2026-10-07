# src/agent/tools/memory.py
"""Memory retrieval tools — semantic and episodic."""

from langchain_core.tools import tool

from agent.memory import get_episodic_memory, get_semantic_memory
from agent.memory.recall import recall_chunks, recall_runs


@tool
def retrieve_memory(query: str) -> str:
    """
    Search past agent interactions and ingested documents for context relevant
    to the query. Returns the top matches with source and relevance score.
    Pass the user's request as phrased; it is rewritten into a search query.
    Use this when the user references something they may have asked before,
    or when background context from prior sessions could improve the answer.
    """
    chunks = recall_chunks(query, get_semantic_memory(), k=5)

    if not chunks:
        return "No relevant memory found."

    parts = [
        f"[{i}] source={chunk.source}, score={chunk.score:.2f}\n{chunk.content}"
        for i, chunk in enumerate(chunks, 1)
    ]
    return "\n\n".join(parts)


@tool
def retrieve_episodic_memory(query: str = "", recent: int = 5) -> str:
    """
    Look up past agent runs from episodic memory.

    If `query` is provided, searches run history by keyword (matches against
    what the user asked and what the agent answered). Pass the user's request
    as phrased; it is rewritten into keyword variants. If `query` is empty,
    returns the `recent` most recent runs.

    Use this when the user asks things like:
    - "what did I ask you yesterday?"
    - "find runs where I asked about email"
    - "show me my last 3 sessions"
    - "did you successfully draft an email last time?"
    """
    mem = get_episodic_memory()

    if query:
        runs = recall_runs(query, mem, n=recent)
        header = f'Runs matching "{query}"'
    else:
        runs = mem.get_recent_runs(n=recent)
        header = f"Last {recent} runs"

    if not runs:
        return "No matching runs found in episodic memory."

    parts = [header]
    for i, run in enumerate(runs, 1):
        tools = ", ".join(run.tools_called) if run.tools_called else "none"
        status = "✓" if run.success else "✗"
        tokens = (
            f"{run.token_usage['total']} tokens" if run.token_usage else "n/a"
        )
        parts.append(
            f"\n[{i}] {status} {run.timestamp[:19].replace('T', ' ')} | tools: {tools} | {tokens}"
            f"\n    Q: {run.user_input}"
            f"\n    A: {run.final_output[:200]}{'…' if len(run.final_output) > 200 else ''}"
        )

    return "\n".join(parts)
