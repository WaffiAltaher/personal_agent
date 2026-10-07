# 11: Agent consumes the Informer server

**What to build:** The agent loads Informer tools the same way as MS365 tools: through the shared loader, with an `informer_` prefix, all read-classified. When Informer credentials aren't configured, the agent starts without them and shows a notice. With `--fixtures`, the Informer server runs against the fake Informer API. Demo: "what's outstanding?" is answered from Informer end to end.

**Blocked by:** 03, 04, 09

**Status:** ready-for-agent

- [ ] Informer tools are bound with the `informer_` prefix and classified as read
- [ ] Missing credentials lead to a notice, and the agent still starts
- [ ] A seam-A test runs the "what's outstanding?" flow against the Fixture world over real MCP
