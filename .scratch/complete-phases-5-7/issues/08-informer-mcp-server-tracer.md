# 08: Informer MCP server tracer bullet

**What to build:** A standalone stdio MCP server for Informer, which the owner authored and any MCP client can use. It uses the Python MCP SDK held below 2.0, because 2.x is incompatible with `langchain-mcp-adapters`. The first slice adds tools to list/search Relations and get one Relation, plus the second Fixture-world piece: a local HTTP fake of Informer API v2 that serves seeded Relations. Rejected credentials come back as a clear tool error naming the settings to check. Tested over the MCP protocol (seam B).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Server package runnable on its own over stdio; configuration is API key, security code and base-URL override
- [ ] Sends the `Apikey` and `Securitycode` headers to Informer API v2
- [ ] The fake Informer API serves seeded Relations and can be switched to return 401
- [ ] Seam-B tests through a real MCP client session: tool discovery, Relation search and get, a credentials error
- [ ] `mcp` dependency pinned below 2.0
