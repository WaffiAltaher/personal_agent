# 02: Model selection + inject the chat model into the graph

**What to build:** The owner picks the agent's model with one `provider:model` setting (for example `google_genai:gemini-3.8-flash` or `anthropic:claude-sonnet-5-5`). The setting goes through LangChain's provider-agnostic chat-model factory, and the default becomes `gemini-3.8-flash`. The graph accepts an injected chat model, which is test seam A in the spec. Existing tests move from patching the Gemini class to injecting a scripted fake model. This is a prefactor for every later ticket.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `provider:model` setting with default `gemini-3.8-flash`; the Anthropic API key is optional and required only when an Anthropic model is selected; a missing key for the chosen provider gives a clear startup error
- [ ] Anthropic provider dependency added
- [ ] `build_graph` accepts an optional chat model and builds one from settings when it isn't given
- [ ] All existing graph and retry tests inject a model; none patch the Gemini class
- [ ] ADR appended to the ADR log: the model change (2.0/2.5 Flash end of life) and the provider-agnostic factory instead of aisuite
- [ ] Full suite green with no network access
