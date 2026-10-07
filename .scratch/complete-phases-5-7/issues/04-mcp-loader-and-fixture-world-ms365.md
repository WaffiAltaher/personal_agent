# 04: MCP loader + Fixture world (stand-in MS365) + `--fixtures` flag

**What to build:** One loader starts all configured MCP servers through `langchain-mcp-adapters` with server-name prefixes, each server optional and isolated. The Fixture world gets its first piece: a small local MCP server that stands in for MS365. It uses the real server's tool names and response shapes for the read tools the agent needs (mail, calendar, contacts) and serves a seeded mailbox, calendar and contacts. A CLI flag runs the agent against the Fixture world. Demo: with `--fixtures`, "what meetings do I have this week and who is attending?" is answered by combining calendar, contacts and mail (plan item 5.3).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Seed data is in versioned fixture files
- [ ] The stand-in MS365 server reproduces the real tool names and shapes for the tools used
- [ ] The CLI `--fixtures` flag points the loader at the Fixture world
- [ ] A seam-A test (scripted model) runs the meetings-and-attendees flow against the stand-in over real MCP
- [ ] ADR appended: Fixture world as the only test and eval target (Informer has no sandbox)
