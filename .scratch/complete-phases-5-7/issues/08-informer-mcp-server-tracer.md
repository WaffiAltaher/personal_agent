# 08: Informer MCP server tracer bullet

**What to build:** A standalone stdio MCP server for Informer, which the owner authored and any MCP client can use. It uses the Python MCP SDK held below 2.0, because 2.x is incompatible with `langchain-mcp-adapters`. The first slice adds tools to list/search Relations and get one Relation, plus the second Fixture-world piece: a local HTTP fake of Informer API v2 that serves seeded Relations. Rejected credentials come back as a clear tool error naming the settings to check. Tested over the MCP protocol (seam B).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] Server package runnable on its own over stdio; configuration is API key, security code and base-URL override
- [x] Sends the `Apikey` and `Securitycode` headers to Informer API v2
- [x] The fake Informer API serves seeded Relations and can be switched to return 401
- [x] Seam-B tests through a real MCP client session: tool discovery, Relation search and get, a credentials error
- [x] `mcp` dependency pinned below 2.0

## Comments

- Server package `src/informer_mcp/` (FastMCP, `mcp>=1.24,<2`). Run: `informer-mcp` or `python -m informer_mcp`; config from `INFORMER_API_KEY`, `INFORMER_SECURITY_CODE`, `INFORMER_BASE_URL` (or `.env`). `create_server(settings)` builds it in-process. Tools: `list_relations(search="")`, `get_relation(relation_id)`, both annotated `readOnlyHint=True`. HTTP errors go through `InformerClient.get` in `client.py` (401 names the settings).
- Fake: `fixture_world.informer_api.FakeInformerApi` (stdlib HTTP server on a free port; `fake.base_url`, `fake.api_key`, `fake.security_code`, `fake.failure = Failure.UNAUTHORIZED`). It only serves data when both headers match. Seeds are in `src/fixture_world/data/informer/*.json`; add routes in `_routes()` and members to `Failure`.
- Seam-B harness `tests/informer_server/conftest.py`: fixtures `fake_informer`, `informer_settings`, `connect` (in-process MCP session), `call_tool`. `test_stdio.py` covers the subprocess launch.
- `list_relations` fetches one page of 100. Paging, the cap and the truncation notice are left to ticket 09.
