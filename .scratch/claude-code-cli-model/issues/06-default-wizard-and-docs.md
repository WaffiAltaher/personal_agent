# 06: Subscription model as the default, plus the wizard and docs

**What to build:** A fresh setup runs on the owner's Claude subscription without asking for chat API keys. The built-in default is `claude_code:claude-sonnet-5-5`, the setup wizard checks the Claude Code login and writes that default, and the project's agent instructions describe it.

**Blocked by:** 01, 05

**Status:** ready-for-agent

- [ ] The built-in default model is `claude_code:claude-sonnet-5-5`
- [ ] The setup wizard checks the Claude Code login and writes `MODEL_NAME=claude_code:claude-sonnet-5-5`
- [ ] The wizard's Gemini and Anthropic chat-key steps are optional ("skip if you use your Claude subscription")
- [ ] `GOOGLE_API_KEY` stays required, with a note that it is for embeddings and should come from a Google project with billing turned off
- [ ] The project's agent instructions name the `claude_code:` provider, `claude auth login`, `CLAUDE_CODE_BINARY` and `CLAUDE_CODE_TIMEOUT_S`
- [ ] Tests and evals inject their own model, so the default change breaks none of them
- [ ] The whole test suite passes

Spec: `../spec.md` (Defaults and setup; Further Notes lists the owner's manual `.env` steps).
