"""
tests/test_chat_model.py

Model selection: one `provider:model` setting picks the agent's chat model.
Building a chat model makes no network call, so these run offline.
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.chat_model import MissingApiKeyError, create_chat_model
from agent.config import Settings, settings


def with_settings(**overrides) -> Settings:
    return settings.model_copy(update=overrides)


def test_default_model_is_gemini_3_8_flash():
    model = create_chat_model(settings=with_settings(model_name=Settings.model_fields["model_name"].default))

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model.endswith("gemini-3.8-flash")


def test_anthropic_model_is_selected_by_provider_prefix():
    model = create_chat_model(
        "anthropic:claude-sonnet-5-5",
        settings=with_settings(anthropic_api_key="sk-ant-dummy"),
    )

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-sonnet-5-5"
    assert model.anthropic_api_key.get_secret_value() == "sk-ant-dummy"  # from settings, not the environment


def test_bare_gemini_name_uses_the_gemini_api_not_vertex():
    # An existing .env may still say MODEL_NAME=gemini-2.5-flash (no provider prefix).
    model = create_chat_model("gemini-2.5-flash", settings=with_settings())

    assert isinstance(model, ChatGoogleGenerativeAI)


def test_anthropic_model_without_api_key_fails_with_a_clear_message():
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        create_chat_model("anthropic:claude-sonnet-5-5", settings=with_settings(anthropic_api_key=None))


def test_model_defaults_to_the_configured_setting():
    model = create_chat_model(settings=with_settings(
        model_name="anthropic:claude-sonnet-5-5", anthropic_api_key="sk-ant-dummy",
    ))

    assert isinstance(model, ChatAnthropic)


def test_graph_builds_the_configured_model_when_none_is_injected(monkeypatch):
    from agent.graph import build_graph

    monkeypatch.setattr(settings, "model_name", "anthropic:claude-sonnet-5-5")
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        build_graph()


def test_bare_claude_name_is_anthropic_and_still_needs_its_key():
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        create_chat_model("claude-sonnet-5-5", settings=with_settings(anthropic_api_key=None))

    model = create_chat_model("claude-sonnet-5-5", settings=with_settings(anthropic_api_key="sk-ant-dummy"))
    assert isinstance(model, ChatAnthropic)
    assert model.anthropic_api_key.get_secret_value() == "sk-ant-dummy"


def test_unknown_bare_model_name_is_rejected_with_a_clear_message():
    with pytest.raises(ValueError, match="provider:model"):
        create_chat_model("gpt-9", settings=with_settings())


def test_unknown_provider_prefix_is_rejected():
    # Any provider we hold no key for would skip the key check entirely.
    with pytest.raises(ValueError, match="provider"):
        create_chat_model("openai:gpt-9", settings=with_settings())
