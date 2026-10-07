# src/agent/memory/recall.py
"""
Memory recall with query rewriting.

The user's request is natural language ("what did I ask about invoices last
week"), but episodic search is a SQL LIKE and semantic search embeds whatever
text it is given. A rewriting model call turns the request into:
  - a semantic query for Chroma
  - a short list of keyword variants for the SQLite episodic search
The literal request is always searched too; results from all queries are
merged, deduplicated and ranked.
"""

import json
import logging
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent.chat_model import create_chat_model
from agent.config import Settings
from agent.config import settings as default_settings
from agent.memory.episodic import EpisodicMemory, RunRecord
from agent.memory.semantic import MemoryChunk, SemanticMemory

logger = logging.getLogger(__name__)


REWRITE_PROMPT = """\
You turn a user's request to search their assistant's memory into search queries.
Reply with JSON only, no prose and no code fence:
{"semantic_query": "<one sentence capturing the topic, for vector search>",
 "keywords": ["<1-5 short keywords or phrases likely to appear verbatim in past questions or answers>"]}
Drop filler such as "what did I ask about" or "last week"; keep names, topics and synonyms."""


@dataclass
class RewrittenQuery:
    semantic_query: str
    keywords: list[str] = field(default_factory=list)


def create_rewrite_model(settings: Settings = default_settings) -> BaseChatModel:
    """The rewriting model: MEMORY_REWRITE_MODEL if set, else the agent's MODEL_NAME."""
    return create_chat_model(settings.memory_rewrite_model, settings=settings)


def rewrite_query(request: str, model: BaseChatModel | None = None) -> RewrittenQuery:
    """
    Ask the rewriting model for a semantic query and keyword variants.

    Without an injected model, the rewriting model is built from settings.
    Never raises: if the model can't be built, the call fails or its reply
    can't be parsed, the literal request is returned as the query, so memory
    search still works.
    """
    try:
        model = model or create_rewrite_model()
        reply = model.invoke([SystemMessage(content=REWRITE_PROMPT), HumanMessage(content=request)])
        text = reply.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        data = json.loads(text)
        return RewrittenQuery(
            semantic_query=str(data["semantic_query"]),
            keywords=[str(k) for k in data["keywords"] if str(k).strip()],
        )
    except Exception as exc:
        logger.warning("Memory query rewriting failed, using the literal query: %s", exc)
        return RewrittenQuery(semantic_query=request)


def recall_runs(
    request: str, episodic: EpisodicMemory, n: int = 5, model: BaseChatModel | None = None
) -> list[RunRecord]:
    """
    Search episodic memory with the literal request plus its keyword variants.

    Runs are deduplicated and ranked by how many queries matched them, then by
    recency (newest first).
    """
    rewritten = rewrite_query(request, model)
    queries = _unique([request, *rewritten.keywords])

    found: dict[str, RunRecord] = {}
    hits: dict[str, int] = {}
    for q in queries:
        for run in episodic.search_runs(q, n=n):
            found.setdefault(run.id, run)
            hits[run.id] = hits.get(run.id, 0) + 1

    ranked = sorted(found.values(), key=lambda r: (hits[r.id], r.timestamp), reverse=True)
    return ranked[:n]


def _unique(queries: list[str]) -> list[str]:
    """Drop blank and case-insensitive duplicate queries, keeping order."""
    seen: set[str] = set()
    result = []
    for q in (q.strip() for q in queries):
        if q and q.lower() not in seen:
            seen.add(q.lower())
            result.append(q)
    return result


def recall_chunks(
    request: str, semantic: SemanticMemory, k: int = 5, model: BaseChatModel | None = None
) -> list[MemoryChunk]:
    """
    Search semantic memory with the literal request and its rewritten semantic query.

    Chunks are deduplicated by content (keeping the best score) and ranked by score.
    """
    rewritten = rewrite_query(request, model)

    best: dict[str, MemoryChunk] = {}
    for q in _unique([request, rewritten.semantic_query]):
        for chunk in semantic.search_all(q, k=k):
            if chunk.content not in best or chunk.score > best[chunk.content].score:
                best[chunk.content] = chunk

    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:k]
