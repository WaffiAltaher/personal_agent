"""
tracing.py — Langfuse observability setup.

This module is the single place where Langfuse is configured.
The rest of the codebase imports `get_callback_handler` and passes
the result into LangGraph's config dict. That's the full interface.

Credentials come from `agent.config` (Pydantic loads `.env`). The Langfuse SDK
reads LANGFUSE_* from `os.environ` only; it does not see Pydantic-loaded
values unless we pass them into `Langfuse(...)`, which we do in `_get_langfuse()`.
"""
from langfuse.types import TraceContext
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from agent.config import settings

_langfuse: Langfuse | None = None


def _get_langfuse() -> Langfuse:
    """
    Singleton Langfuse client using keys from Settings (`.env` via Pydantic).

    Without this, `get_client()` / `CallbackHandler()` can run before any key is
    in `os.environ`, yielding a disabled client and "no public_key" warnings.
    """
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
        )
    return _langfuse


def verify_connection() -> bool:
    """
    Check that Langfuse credentials are valid at startup.
    Fails loudly rather than silently dropping traces.
    """
    return _get_langfuse().auth_check()


def get_callback_handler(trace_id: str) -> CallbackHandler:
    """
    Return a configured Langfuse CallbackHandler for a single agent run.

    Each call to this function produces a fresh handler, which means
    a fresh trace in Langfuse. Call it once per agent invocation.

    Langfuse v4's handler only accepts `public_key` and `trace_context`.
    Pass session_id, user_id, and trace_name via `propagate_attributes(...)`
    around the graph `invoke` (see cli.py).
    """
    _get_langfuse()
    return CallbackHandler(public_key=settings.langfuse_public_key, trace_context=TraceContext(trace_id=trace_id))


def flush_traces() -> None:
    """Batch-export any buffered spans to Langfuse."""
    _get_langfuse().flush()