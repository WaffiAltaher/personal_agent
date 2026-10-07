# 02: Model selection + inject the chat model into the graph

**What to build:** The owner picks the agent's model with one `provider:model` setting (for example `google_genai:gemini-3.8-flash` or `anthropic:claude-sonnet-5-5`). The setting goes through LangChain's provider-agnostic chat-model factory, and the default becomes `gemini-3.8-flash`. The graph accepts an injected chat model, which is test seam A in the spec. Existing tests move from patching the Gemini class to injecting a scripted fake model. This is a prefactor for every later ticket.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] `provider:model` setting with default `gemini-3.8-flash`; the Anthropic API key is optional and required only when an Anthropic model is selected; a missing key for the chosen provider gives a clear startup error
- [x] Anthropic provider dependency added
- [x] `build_graph` accepts an optional chat model and builds one from settings when it isn't given
- [x] All existing graph and retry tests inject a model; none patch the Gemini class
- [x] ADR appended to the ADR log: the model change (2.0/2.5 Flash end of life) and the provider-agnostic factory instead of aisuite
- [x] Full suite green with no network access

## Comments

- `MODEL_NAME` is the `provider:model` setting (default `google_genai:gemini-3.8-flash`). `agent.chat_model.create_chat_model(model=None, *, settings=...)` builds it via `init_chat_model`, passing keys from settings. A bare `gemini-*` name maps to `google_genai`, because `init_chat_model` would infer Vertex AI. `MissingApiKeyError` names the missing setting, and the CLI prints it and exits 1 before any MCP server starts.
- `build_graph(checkpointer=None, tools=None, model=None)`. The module-level `agent_graph` was removed because building a model at import time made a missing key crash the import. Tests inject a model through the `scripted_model` fixture in `tests/conftest.py`.
- Added `langchain-anthropic` 1.7.5, which raised `langchain-core` from 1.3.0 to 1.6.7. Added ADR-009. The suite was verified with outbound sockets blocked.
- Left for the owner: learning lesson 0003 still patches `agent.graph.ChatGoogleGenerativeAI`. The owner's `.env` `MODEL_NAME="gemini-2.5-flash"` still works but should move to `google_genai:gemini-3.8-flash`.
