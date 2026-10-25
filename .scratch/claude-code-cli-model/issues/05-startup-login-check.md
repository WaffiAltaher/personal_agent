# 05: Startup checks the Claude Code login

**What to build:** When the owner starts the agent in real mode with a `claude_code:` agent or judge model, startup checks the Claude Code login before the run, the way it already checks the Google login. A missing CLI, or a login that isn't a claude.ai subscription, stops startup with the one step that fixes it.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The check runs only in real mode, and only when the agent model or the judge model is `claude_code:`
- [ ] It asks the CLI (through `CLAUDE_CODE_BINARY`, with the API-key variables removed) for its login status, and requires a logged-in claude.ai login
- [ ] Logged out, or logged in with an API key: startup stops and names `claude auth login`
- [ ] No binary: startup stops with "Claude Code not found on PATH"
- [ ] The check uses no model usage
- [ ] Tests through the CLI harness with the stand-in cover all four cases
- [ ] The whole test suite passes

Traps:
- Run the check under the same environment rules as a model call. Otherwise an exported API key could make the login look different from what the run will use.

Spec: `../spec.md` (Startup check).
