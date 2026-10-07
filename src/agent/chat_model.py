# src/agent/chat_model.py
"""
chat_model.py — Build the agent's chat model from a `provider:model` setting.

The provider prefix picks the LangChain integration via init_chat_model, e.g.
  google_genai:gemini-3.8-flash   → ChatGoogleGenerativeAI (Gemini API)
  anthropic:claude-sonnet-5-5     → ChatAnthropic
A bare Gemini name (e.g. an older .env's "gemini-2.5-flash") is treated as
google_genai: init_chat_model would otherwise infer Vertex AI for it.

API keys come from settings, not the process environment, so a missing key
fails here with a clear message instead of deep inside the provider SDK.
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from agent.config import Settings
from agent.config import settings as default_settings


class MissingApiKeyError(RuntimeError):
    """The selected model's provider has no API key configured."""


# provider → (Settings field holding its key, init kwarg the integration expects)
_PROVIDER_KEYS: dict[str, tuple[str, str]] = {
    "google_genai": ("google_api_key", "google_api_key"),
    "anthropic": ("anthropic_api_key", "api_key"),
}


def create_chat_model(model: str | None = None, *, settings: Settings = default_settings) -> BaseChatModel:
    """Return a chat model for `model` (`provider:model`), defaulting to settings.model_name."""
    spec = model or settings.model_name
    provider, sep, name = spec.partition(":")
    if not sep:
        provider, name = ("google_genai" if spec.lower().startswith("gemini") else ""), spec

    kwargs = {}
    if provider in _PROVIDER_KEYS:
        field, kwarg = _PROVIDER_KEYS[provider]
        key = getattr(settings, field)
        if not key:
            raise MissingApiKeyError(
                f"Model '{spec}' needs {field.upper()}, which is not set. "
                "Add it to .env, or pick another model with MODEL_NAME."
            )
        kwargs[kwarg] = key

    return init_chat_model(name, model_provider=provider or None, **kwargs)
