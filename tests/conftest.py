# tests/conftest.py
"""Dummy credentials so the suite runs without a real .env (e.g. in a fresh worktree)."""

import os

for _key in (
    "GOOGLE_API_KEY",
    "TAVILY_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "MS365_MCP_CLIENT_ID",
    "MS365_MCP_TENANT_ID",
):
    os.environ.setdefault(_key, "test-dummy")


import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(GenericFakeChatModel):
    """Fake chat model that replies with pre-scripted AIMessages, in order.

    A scripted reply may also be a function of the messages the model is shown,
    returning the AIMessage, for steps that act on what a tool returned.

    bind_tools is a no-op so build_graph can bind tools to it like a real model.
    Inject it with build_graph(model=...) instead of patching a provider class.
    """

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        reply = next(self.messages)
        if callable(reply):
            reply = reply(messages)
        message = AIMessage(content=reply) if isinstance(reply, str) else reply
        return ChatResult(generations=[ChatGeneration(message=message)])


# The real Claude Code CLI spends the owner's subscription: outside `live` tests, a claude_code:
# model or login check that a test didn't point at the stand-in fails with "not found" instead.
NO_REAL_CLAUDE = "/nonexistent/the-real-claude-is-not-called-in-tests"


@pytest.fixture(autouse=True)
def no_real_claude_code(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return
    from agent.config import settings

    monkeypatch.setenv("CLAUDE_CODE_BINARY", NO_REAL_CLAUDE)
    monkeypatch.setattr(settings, "claude_code_binary", NO_REAL_CLAUDE)


@pytest.fixture(autouse=True)
def owner_types_nothing_more(monkeypatch):
    """A CLI session in a test ends at its first `> ` prompt (Ctrl-D) unless the test types
    lines with `_cli_harness.type_lines`."""
    from _cli_harness import type_lines

    type_lines(monkeypatch, [])


@pytest.fixture
def startup_login_checks_pass(monkeypatch):
    """Every real-mode CLI startup login check passes without running. A test of one check
    sets that check again after requesting this."""
    import agent.cli as cli

    monkeypatch.setattr(cli, "check_google_login", lambda: None)
    monkeypatch.setattr(cli, "check_claude_code_login", lambda binary: None)


@pytest.fixture
def scripted_model():
    """Factory: scripted_model([AIMessage(...), ...]) -> a fake model replying with those messages."""
    return lambda responses: ScriptedChatModel(messages=iter(responses))


@pytest.fixture
def langfuse_spans(monkeypatch):
    """Spans the agent's Langfuse handler records, captured in memory: nothing is sent anywhere.

    Returns a function listing the finished spans."""
    import uuid

    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    import agent.tracing as tracing

    # Langfuse keeps one client per public key for the process: a fresh key per test gives
    # each test its own client, wired to its own exporter.
    monkeypatch.setattr(tracing.settings, "langfuse_public_key", f"pk-test-{uuid.uuid4().hex}")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    client = Langfuse(
        public_key=tracing.settings.langfuse_public_key,
        secret_key="test-dummy",
        base_url="http://127.0.0.1:9",  # never reached: Langfuse's own exporter exports nothing
        tracer_provider=provider,
        should_export_span=lambda span: False,
    )
    monkeypatch.setattr(tracing, "_langfuse", client)
    return exporter.get_finished_spans
