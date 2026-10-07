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


class ScriptedChatModel(GenericFakeChatModel):
    """Fake chat model that replies with pre-scripted AIMessages, in order.

    bind_tools is a no-op so build_graph can bind tools to it like a real model.
    Inject it with build_graph(model=...) instead of patching a provider class.
    """

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def scripted_model():
    """Factory: scripted_model([AIMessage(...), ...]) -> a fake model replying with those messages."""
    return lambda responses: ScriptedChatModel(messages=iter(responses))
