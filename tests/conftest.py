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


@pytest.fixture
def scripted_model():
    """Factory: scripted_model([AIMessage(...), ...]) -> a fake model replying with those messages."""
    return lambda responses: ScriptedChatModel(messages=iter(responses))
