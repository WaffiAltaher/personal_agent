# 02: Web server, password login and request checks

**What to build:** `python -m agent.web` starts a FastAPI server on `127.0.0.1:<WEB_PORT>`, serving the built React app from `web/dist` (Vite + TypeScript, in a top-level `web/` folder). For now, after login, the app shows an empty shell where the Conversation list will go. The owner sets a password with `python -m agent.web.set_password`, which writes an argon2id hash to `.env` as `WEB_PASSWORD_HASH`. Login sets a 7-day signed `HttpOnly` / `SameSite=Strict` session cookie, and logout clears it. Every request is checked for `Host`, every state-changing request and event stream for `Origin`, and failed logins are rate-limited. Startup runs the CLI's checks (model, Langfuse, Google and Claude Code logins, tool loading with notices) through a module shared with `cli.py`, so the messages are identical. The app is built by a factory that takes graph, tools, model and checkpoint path, so tests inject the Fixture world.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] With no `WEB_PASSWORD_HASH`, startup stops naming `python -m agent.web.set_password`; with a missing `web/dist`, it stops naming the build command
- [ ] `set_password` reads the password twice without echo and writes or replaces only that line in `.env`
- [ ] A correct password sets the cookie with the stated flags; a wrong one is refused; repeated failures are rate-limited
- [ ] Changing the password ends existing sessions (signing key derived from the hash)
- [ ] Every API endpoint except login refuses requests without a session
- [ ] Wrong `Host` is refused everywhere; a foreign or missing `Origin` is refused on state-changing requests and event streams; no CORS headers
- [ ] Dead Google or Claude Code logins stop startup with the same message as the CLI; skipped MCP servers print the same notices
- [ ] The bind host is a setting defaulting to `127.0.0.1`
- [ ] Vite dev server proxies to FastAPI; one build command produces `web/dist`
- [ ] pytest covers all of the above with FastAPI's test client; no live calls
- [ ] The setup wizard has a step that runs `set_password`; `CLAUDE.md` documents the run and build commands and the `WEB_*` settings

Spec: `../spec.md` (Server and app, Login).

## Comments
