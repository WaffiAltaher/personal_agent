# src/agent/memory/__init__.py
import shutil
import tempfile
from contextlib import contextmanager

from agent.memory.budget import ContextBudgetManager, TokenCounter
from agent.memory.episodic import EpisodicMemory, RunRecord
from agent.memory.semantic import MemoryChunk, SemanticMemory

__all__ = [
    "EpisodicMemory",
    "SemanticMemory",
    "ContextBudgetManager",
    "TokenCounter",
    "RunRecord",
    "MemoryChunk",
    "get_episodic_memory",
    "get_semantic_memory",
]

# ---------------------------------------------------------------------------
# Module-level lazy singletons
# Both graph.py and tools/memory.py import these so they share one instance.
# ---------------------------------------------------------------------------

_episodic: EpisodicMemory | None = None
_semantic: SemanticMemory | None = None


def get_episodic_memory() -> EpisodicMemory:
    global _episodic
    if _episodic is None:
        _episodic = EpisodicMemory()
    return _episodic


def get_semantic_memory() -> SemanticMemory:
    global _semantic
    if _semantic is None:
        _semantic = SemanticMemory()
    return _semantic


@contextmanager
def fixtures_semantic_memory():
    """Temp Chroma store for Fixture-world runs; restores the owner's store after."""
    global _semantic
    prev = _semantic
    tmp = tempfile.mkdtemp(prefix="fixture-chroma-")
    _semantic = SemanticMemory(persist_dir=tmp)
    try:
        yield
    finally:
        _semantic = prev
        shutil.rmtree(tmp, ignore_errors=True)
