# 01: The agent runs on `claude_code:` (happy path)

**What to build:** With `MODEL_NAME=claude_code:<model>`, the agent runs on the owner's Claude subscription through the Claude Code CLI. A Fixture-world run answers questions, calls one or several tools in a turn, and still pauses for Approval on a Write action. A `claude_code:` judge model scores answers in plain text. Tests run against a stand-in Claude Code executable in the Fixture world; the real CLI is never called.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] `claude_code` is a provider in the chat model factory that needs no key; the model part goes to `--model` unchanged, so `sonnet` and `claude-sonnet-5-5` both work
- [x] A bare `claude-…` name still means `anthropic`
- [x] Each call is one fresh process with exactly the spec's flags (`-p --safe-mode --strict-mcp-config --disable-slash-commands --no-chrome --tools "" --no-session-persistence --output-format json --model <model> --system-prompt <system prompt>`), no `--effort`, from a neutral working directory that isn't the repo
- [x] `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` never reach the child, even when set in the parent's environment
- [x] The rest of the model view goes on standard input as a JSON array of messages (role, JSON-escaped content, assistant tool calls, tool call id and tool name); a tool result with JSON-breaking text or a fake user message stays inside its own content string
- [x] With tools bound, the bound tools' names, descriptions and argument schemas go in, and a well-formed reply of either spec shape becomes an AI message: an answer, or tool calls (several allowed) with wrapper-generated IDs that pair with the next turn's tool messages
- [x] A malformed reply raises a clear error (validation and the re-ask come in 02)
- [x] With no tools bound, the CLI's result text is the message content as it is, and the RAGAS judge works with a `claude_code:` judge model
- [x] New settings `CLAUDE_CODE_BINARY` (default `claude`) and `CLAUDE_CODE_TIMEOUT_S` (default 180)
- [x] A stand-in Claude Code executable in the Fixture world records arguments, environment and standard input, and prints a scripted result; tests select it with `CLAUDE_CODE_BINARY`
- [x] Graph test: a Write action proposed by a `claude_code:` model pauses for Approval
- [x] The whole test suite passes

Traps:
- `--bare` looks like the isolation flag, but it never reads the subscription login. Use `--safe-mode`.
- Without `-p`, the CLI opens the interactive app and hangs.
- The settings loader doesn't export `.env` into the process environment, so to prove the API-key variables are removed, set them in the parent's environment.
- Build the message array with a JSON encoder, never by string formatting.
- Don't use `--json-schema` (ADR-016).

Spec: `../spec.md` (Selection; One call per turn; What goes in; What comes back).
