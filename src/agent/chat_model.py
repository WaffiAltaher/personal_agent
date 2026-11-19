# src/agent/chat_model.py
"""
chat_model.py — Build the agent's chat model from a `provider:model` setting.

The provider prefix picks the LangChain integration via init_chat_model, e.g.
  google_genai:gemini-3.8-flash   → ChatGoogleGenerativeAI (Gemini API)
  anthropic:claude-sonnet-5-5     → ChatAnthropic
  claude_code:sonnet              → ClaudeCodeChatModel (the owner's Claude subscription; no key)
A bare Gemini name (e.g. an older .env's "gemini-2.5-flash") is treated as
google_genai: init_chat_model would otherwise infer Vertex AI for it. A bare
Claude name is treated as anthropic. Any other bare name, or a provider we hold
no key for, is rejected, so a model is never built without the key check.

API keys come from settings, not the process environment, so a missing key
fails here with a clear message instead of deep inside the provider SDK.

Every API request gets settings.model_timeout_s: the Gemini and Anthropic integrations (and
the Google embeddings) otherwise wait forever on a request the server never answers.
"""

from google import genai
from google.genai.types import HttpOptions
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from agent.claude_code_model import ClaudeCodeChatModel
from agent.config import Settings
from agent.config import settings as default_settings


class ModelConfigError(RuntimeError):
    """The model setting can't be turned into a chat model."""


class MissingApiKeyError(ModelConfigError):
    """The selected model's provider has no API key configured."""


class UnsupportedModelError(ModelConfigError, ValueError):
    """The model setting names no provider we hold a key for."""


# provider → (Settings field holding its key, init kwarg the integration expects)
_PROVIDER_KEYS: dict[str, tuple[str, str]] = {
    "google_genai": ("google_api_key", "google_api_key"),
    "anthropic": ("anthropic_api_key", "api_key"),
}

# bare model-name prefix → provider
_BARE_NAME_PROVIDERS: dict[str, str] = {
    "gemini": "google_genai",
    "claude": "anthropic",
}


def is_claude_code_model(model: str | None) -> bool:
    """Whether `model` (`provider:model`) runs through the Claude Code CLI."""
    return (model or "").startswith("claude_code:")


def create_chat_model(model: str | None = None, *, settings: Settings = default_settings) -> BaseChatModel:
    """Return a chat model for `model` (`provider:model`), defaulting to settings.model_name."""
    spec = model or settings.model_name
    provider, sep, name = spec.partition(":")
    if not sep:
        provider = next((p for prefix, p in _BARE_NAME_PROVIDERS.items() if spec.lower().startswith(prefix)), "")
        name = spec
    if is_claude_code_model(spec):
        return ClaudeCodeChatModel(
            model=name, binary=settings.claude_code_binary, timeout_s=settings.claude_code_timeout_s,
        )
    if provider not in _PROVIDER_KEYS:
        raise UnsupportedModelError(
            f"Model '{spec}' has no supported provider. Use provider:model with one of "
            f"{', '.join(sorted([*_PROVIDER_KEYS, 'claude_code']))}, e.g. anthropic:claude-sonnet-5-5."
        )

    field, kwarg = _PROVIDER_KEYS[provider]
    key = getattr(settings, field)
    if not key:
        raise MissingApiKeyError(
            f"Model '{spec}' needs {field.upper()}, which is not set. "
            "Add it to .env, or pick another model with MODEL_NAME."
        )

    return init_chat_model(name, model_provider=provider, timeout=settings.model_timeout_s, **{kwarg: key})


def create_embeddings(*, settings: Settings = default_settings) -> GoogleGenerativeAIEmbeddings:
    """The Google embeddings (semantic memory, RAGAS answer relevancy), with a request timeout."""
    embeddings = GoogleGenerativeAIEmbeddings(
        model=settings.chroma_embedding_model, google_api_key=settings.google_api_key,
    )
    # The integration takes no timeout, so its client is replaced by one with the same key and a
    # timeout (HttpOptions.timeout is in milliseconds).
    embeddings.client = genai.Client(
        api_key=settings.google_api_key,
        http_options=HttpOptions(timeout=int(settings.model_timeout_s * 1000)),
    )
    return embeddings
