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

Retries: every model, and the Google embeddings, tries a failed request settings.model_attempts
times in all (the first included). The Anthropic SDK retries timeouts, dropped connections,
408/409/429 and 5xx itself. The Google SDK retries only error replies (408/429/5xx), so a Google
request that timed out or lost its connection (GOOGLE_NETWORK_ERRORS) is retried here: the chat
model's call by the graph (model_binding.with_network_retry), the embeddings by
RetryingGoogleEmbeddings. A claude_code: model reruns a CLI call that timed out.
"""

import aiohttp
import httpx
import tenacity
from google import genai
from google.genai.types import HttpOptions, HttpRetryOptions
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from agent.claude_code_model import ClaudeCodeChatModel
from agent.config import Settings
from agent.config import settings as default_settings


# A Google request that failed without a reply from Google, which the Google SDK does not retry.
# The SDK sends sync requests with httpx and async ones (the graph's) with aiohttp, whose timeout
# is the built-in TimeoutError.
GOOGLE_NETWORK_ERRORS: tuple[type[Exception], ...] = (
    httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError,
    TimeoutError, aiohttp.ClientConnectionError,
)


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
            attempts=settings.model_attempts,
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

    # Both integrations call it max_retries, but langchain-google-genai passes it to the Google SDK
    # as the number of attempts, while the Anthropic SDK counts retries after the first attempt.
    max_retries = settings.model_attempts if provider == "google_genai" else settings.model_attempts - 1
    return init_chat_model(
        name, model_provider=provider, timeout=settings.model_timeout_s, max_retries=max_retries, **{kwarg: key},
    )


def _is_network_error(exc: BaseException) -> bool:
    """A GOOGLE_NETWORK_ERRORS failure, also when the embeddings integration wrapped it in its
    own GoogleGenerativeAIError (it wraps every error, keeping the original as the cause)."""
    return isinstance(exc, GOOGLE_NETWORK_ERRORS) or isinstance(exc.__cause__, GOOGLE_NETWORK_ERRORS)


def _network_retry(attempts: int) -> dict:
    """tenacity arguments: retry GOOGLE_NETWORK_ERRORS with backoff, then re-raise the last one."""
    return dict(
        retry=tenacity.retry_if_exception(_is_network_error),
        stop=tenacity.stop_after_attempt(attempts),
        wait=tenacity.wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )


class RetryingGoogleEmbeddings(GoogleGenerativeAIEmbeddings):
    """Google embeddings whose requests are retried on GOOGLE_NETWORK_ERRORS."""

    attempts: int = 1  # the first included

    def embed_documents(self, *args, **kwargs):
        for attempt in tenacity.Retrying(**_network_retry(self.attempts)):
            with attempt:
                return super().embed_documents(*args, **kwargs)

    def embed_query(self, *args, **kwargs):
        for attempt in tenacity.Retrying(**_network_retry(self.attempts)):
            with attempt:
                return super().embed_query(*args, **kwargs)

    async def aembed_documents(self, *args, **kwargs):
        async for attempt in tenacity.AsyncRetrying(**_network_retry(self.attempts)):
            with attempt:
                return await super().aembed_documents(*args, **kwargs)

    async def aembed_query(self, *args, **kwargs):
        async for attempt in tenacity.AsyncRetrying(**_network_retry(self.attempts)):
            with attempt:
                return await super().aembed_query(*args, **kwargs)


def create_embeddings(*, settings: Settings = default_settings) -> GoogleGenerativeAIEmbeddings:
    """The Google embeddings (semantic memory, RAGAS answer relevancy), with a request timeout
    and retries."""
    embeddings = RetryingGoogleEmbeddings(
        model=settings.chroma_embedding_model, google_api_key=settings.google_api_key,
        attempts=settings.model_attempts,
    )
    # The integration takes no timeout or retry options, so its client is replaced by one with the
    # same key, a timeout (HttpOptions.timeout is in milliseconds) and the SDK's retry of 408/429/5xx.
    embeddings.client = genai.Client(
        api_key=settings.google_api_key,
        http_options=HttpOptions(
            timeout=int(settings.model_timeout_s * 1000),
            retry_options=HttpRetryOptions(attempts=settings.model_attempts),
        ),
    )
    return embeddings
