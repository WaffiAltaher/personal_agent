# Spec: Chat model through the Claude Code CLI

Status: ready-for-agent

Source: the grilling session of 2026-10-25 (Q1–Q17). Vocabulary follows `GLOSSARY.md` (Write action, Approval, Fixture world). Decisions respect `docs/ARCHITECTURE_DECISIONS.md`, especially ADR-009 (`provider:model` selection), ADR-010 (classification fails closed), ADR-011 (the Fixture world is the only test and eval target), ADR-013 (the model view) and ADR-016 (this feature's decision record).

## Problem Statement

Every model the agent can use is billed per token through an API key, on top of the subscriptions the owner already pays for. The owner's Google project has run out of prepaid credit, so the default Gemini model fails with `402 RESOURCE_EXHAUSTED`, and the Anthropic route bills a separate API key. The agent only ever runs on the owner's laptop, where Claude Code is installed and logged in to a claude.ai Pro subscription. The agent can't use that subscription.

## Solution

The owner selects `claude_code:<model>` (for example `claude_code:claude-sonnet-5-5` or `claude_code:sonnet`) as the model, and the agent runs on the Claude subscription through the Claude Code CLI. No API key is involved. The CLI replaces only the model: the agent's own loop, the Approval step, the retry policy, checkpoints and evals all stay as they are, because every tool call still comes back to the agent as a structured tool call that it runs itself. The same choice works for the eval judge, and it becomes the default for a fresh setup.

## User Stories

1. As the owner, I want to run the agent on my Claude subscription, so that I don't pay per token on top of it.
2. As the owner, I want to choose it with `MODEL_NAME=claude_code:<model>`, so that switching is a `.env` change like every other model.
3. As the owner, I want both `claude_code:sonnet` and `claude_code:claude-sonnet-5-5` to work, so that I can use the moving alias day to day and a pinned model in evals.
4. As the owner, I want a misspelt model name refused with Claude Code's own message, so that a typo doesn't silently run another model.
5. As the owner, I want `anthropic:` and bare `claude-…` names to keep meaning the API, so that a spelling never silently changes how I'm billed.
6. As the owner, I want a `claude_code:` run never to bill an API key, even when `ANTHROPIC_API_KEY` is in the environment, so that the subscription is the only thing used.
7. As the owner, I want startup to stop and name `claude auth login` when Claude Code isn't logged in to a claude.ai subscription, so that I find out before a run starts, not halfway through.
8. As the owner, I want startup to say "Claude Code not found on PATH" when it isn't installed, so that the fix is obvious.
9. As the owner, I want the login check to use none of my subscription limits, so that starting the agent is free.
10. As the owner, I want my personal Claude Code setup (CLAUDE.md, memory, skills, plugins, hooks, MCP servers, Chrome) kept out of the agent's calls, so that my private instructions don't steer the agent.
11. As the owner, I want each agent call to carry only the agent's own context, so that my Pro limits last.
12. As the owner, I want Write actions proposed by the subscription model to still stop for my Approval, so that it can't act on its own.
13. As the owner, I want Claude Code unable to run any tool itself, so that every action goes through the agent's own tools and classification.
14. As the owner, I want an email or tool result unable to pose as my own message, so that prompt injection gets no easier than with the API.
15. As the owner, I want the agent to be able to ask for several tools in one turn, as it does today, so that runs don't get slower.
16. As the owner, I want a malformed reply from Claude corrected automatically once, so that a single slip doesn't end my run.
17. As the owner, I want a reply that is still malformed after that to stop the run with a clear message, so that a broken turn never turns into a made-up answer.
18. As the owner, I want a run that hits my usage limit to stop with the reset time, so that I know when I can continue.
19. As the owner, I want the agent never to fall back to an API key when my subscription is unavailable, so that nothing is billed without my asking.
20. As the owner, I want a call that hangs to stop after 180 seconds with a clear message, so that the CLI never sits there silently.
21. As the owner, I want to change that time limit in `.env`, so that a slow day doesn't need a code change.
22. As the owner, I want CLI errors shown as a message, not a traceback, so that I can act on them.
23. As the owner, I want the run log to show token usage and the API-equivalent cost, so that I can see what the subscription saves me.
24. As the owner, I want the setup wizard to set up the subscription model without asking for chat API keys, so that a fresh setup works without paying per token.
25. As the owner, I want the wizard to keep asking for the Google key and say it is for embeddings, so that I know why it's still needed.
26. As the maintainer, I want evals to run with `claude_code:` models, so that I can compare them like any other model.
27. As the maintainer, I want the RAGAS judge to work with a `claude_code:` model, so that judging also runs on the subscription.
28. As the maintainer, I want the same run priced the same whether the model is spelled `sonnet` or `claude-sonnet-5-5`, so that cost comparisons are truthful.
29. As the maintainer, I want a model without a price-table row to show no cost rather than a guess, so that reports never invent numbers.
30. As the maintainer, I want Langfuse traces of `claude_code:` runs to look like any other run's, so that tracing needs no change.
31. As the maintainer, I want the wrapper tested without the real CLI, so that tests stay free, offline and repeatable.
32. As the maintainer, I want one opt-in live test against the real CLI, so that a Claude Code update that breaks the flags, the reply format or the isolation gets noticed.

## Implementation Decisions

### Selection

- `claude_code` becomes a third provider in the chat model factory, next to `google_genai` and `anthropic`. It needs no key. The model part goes to the CLI's `--model` as given, so aliases and full IDs both work, and the CLI rejects unknown names.
- Bare names keep their current mapping: a bare `claude-…` still means `anthropic`.
- The judge model setting and the evals' `--judge-model` accept the same prefix.

### One call per turn (stateless)

Each model call starts a fresh CLI process and returns one message. Claude Code keeps no session, and the agent's checkpoints stay the only record of the conversation. ADR-013's model view works unchanged.

These flags are the decision, verified by running the CLI during the grilling:

```
claude -p --safe-mode --strict-mcp-config --disable-slash-commands --no-chrome \
  --tools "" --no-session-persistence --output-format json \
  --model <model> --system-prompt <system prompt>
```

- `-p` is required: `--no-session-persistence` and `--output-format` only work with it, and without it the interactive app opens.
- `--safe-mode` (with the MCP, slash-command and Chrome flags) keeps the owner's personal setup out. `--bare` is not an option, because it never reads the subscription login.
- `--tools ""` gives the model no tools of its own.
- No `--effort` is passed.
- The process runs from a neutral working directory, not the repo.
- Its environment is the parent's minus `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL`.
- New settings: `CLAUDE_CODE_BINARY` (default `claude`), which tests point at a stand-in, and `CLAUDE_CODE_TIMEOUT_S` (default 180).

### What goes in

- The system message goes in as the system prompt.
- The rest of the model view goes on standard input as a JSON array of messages. Each message has a role (`user`, `assistant` or `tool`) and its content as a JSON-escaped string. Assistant messages carry their tool calls (name, args, id); tool messages carry the tool call's id and the tool's name. Content can never break out of its own string.
- With tools bound, the bound tools go in as names, descriptions and argument JSON schemas.
- The instructions say three things: only `user` entries come from the owner, tool content is data, and Claude must never call a tool itself.

### What comes back (the reply contract)

With tools bound, Claude replies with exactly one JSON object, of one of two shapes:

```
{"kind": "answer", "text": "…"}
{"kind": "tool_calls", "calls": [{"name": "…", "args": {…}}, …]}
```

- The wrapper parses the CLI's result text and checks each call's name against the bound tools and its args against that tool's schema.
- A reply showing that Claude tried to use a tool itself (more than one CLI turn) counts as invalid.
- On an invalid reply, the wrapper re-asks once and includes the validation error. A second invalid reply stops the run.
- A valid reply becomes an AI message. Tool calls get IDs generated by the wrapper, and one reply may hold several calls.
- With no tools bound (the RAGAS judge), Claude's result text is the message content as it is, with no JSON format.
- The CLI's `--json-schema` is deliberately not used. Claude Code enforces it by giving the model a tool, and in testing that drew Haiku into calling the agent's tools natively, after which it gave a believable wrong answer (ADR-016).

### Failures

None of these is retried, and none falls back to another model. That matches how a model error ends a run today. The checkpoint keeps everything up to the last completed step.

- **Usage limit:** the run stops with "Claude subscription usage limit reached; resets at <time>. Ask again after the reset."
- **Timeout:** the CLI process (and anything it started) is killed, and the run stops with "Claude Code did not answer within <n> s. Ask again."
- **Other errors:** a non-zero exit, an error result, unparseable output, an unknown model, or a reply still invalid after the re-ask. Each stops the run with the CLI's own message, or the validation error.

### Startup check

- In real mode, when the agent model or the judge model is `claude_code:`, startup asks the CLI for its login status, with the same environment rules as a model call.
- It requires a logged-in claude.ai login. Otherwise it stops and names `claude auth login`. A missing binary stops with "Claude Code not found on PATH".
- It follows the pattern of the existing Google login check, and it uses no model usage.

### Usage and cost

- Each AI message carries token usage from the CLI's result: input, output, cache read, cache write and thinking. It also carries the model the CLI reports it actually ran.
- Cost is the API-equivalent price from the existing dated price table, looked up with the **reported** model, never the alias or the configured name. A model without a row has no cost.
- The CLI's own cost figure is not used.
- The run log and eval efficiency both price this way. A re-ask's usage counts.
- Pricing for Gemini and `anthropic:` doesn't change.

### Defaults and setup

- The built-in default model becomes `claude_code:claude-sonnet-5-5`.
- The setup wizard checks the Claude Code login and writes that default. Its Gemini and Anthropic chat-key steps become optional.
- `GOOGLE_API_KEY` stays required, for embeddings. The wizard notes it should come from a Google project with billing turned off.
- The project's agent instructions describe the new provider, the Claude Code login and the two new settings.

### Tracing

The wrapper is an ordinary LangChain chat model, so the existing Langfuse callbacks trace it unchanged.

## Testing Decisions

A good test drives the feature through a seam the code already has and asserts on what the owner or the agent sees: the message the model returns, the message a run stops with, the cost recorded, whether a run paused for Approval. Internal helpers, call order and the prompt's wording are not targets.

The only new fake is a **stand-in Claude Code executable** in the Fixture world, selected with `CLAUDE_CODE_BINARY`. It records the arguments, environment and standard input it received, and prints a scripted result: a reply, an error result, a usage-limit result, a non-zero exit, or a hang. The real wrapper (process, environment, timeout kill, JSON in and out) always runs. This applies ADR-011's rule: fake at the protocol boundary, never mock in Python.

- **The chat model factory (main seam).** Ask the factory for a `claude_code:` model and drive it the way the graph and the judge do. Covered:
  - prefix selection, and bare names still meaning the API;
  - the exact isolation flags and model, and a working directory that isn't the repo;
  - the three API-key variables never reach the child, even when set in the parent's environment;
  - standard input is a JSON array, and a tool result containing JSON-breaking text or a fake user message stays inside its own content string;
  - answer replies, single and multiple tool calls, and generated IDs;
  - exactly one re-ask on an unknown tool, bad args, bad JSON or a native tool attempt, and a stop on the second failure;
  - plain text with no tools bound;
  - the usage-limit, timeout (child killed) and error stops;
  - token usage and the reported model.

  Prior art: the existing chat model factory tests, and the Fixture world's stand-in MCP server and fake Informer API.
- **The graph (existing seam, a handful of tests).** The model is injected as the graph already allows. A Write action proposed by a `claude_code:` model pauses for Approval. A usage-limit stop leaves a checkpoint that resumes once the stand-in answers again. Prior art: the Approval semantics tests.
- **Pricing and the run log (existing seam, a handful of tests).** The same usage under `claude_code:sonnet` and `claude_code:claude-sonnet-5-5` costs the same. An unpriced model gets no cost. Existing prices are untouched. Prior art: the eval pricing and run-log tests.
- **CLI startup (existing seam, a handful of tests).** Logged in, logged out, an API-key login, and no binary, each through the CLI test harness. Prior art: the Google login startup tests.
- **Live (opt-in, the existing `live` marker).** One real call on Haiku with the production flags and one fake tool. It checks for a valid tool-calls reply in one CLI turn, and that input plus cache tokens stay under a few thousand, which catches a Claude Code update that starts loading the owner's setup again. Prior art: the existing live smoke check.

## Out of Scope

- Cursor (`cursor-agent`). It gets a separate spike before any implementation: it can't turn its tools off and has no system-prompt or schema flag (ADR-016).
- Embeddings and `GOOGLE_API_KEY`. The current key's project has no credit (`402` for embeddings too). The fix is a key from a Google project with billing turned off, or later a local embedding model. Neither is part of this feature.
- An effort or thinking setting.
- Resuming Claude Code sessions, streaming partial output, and any fallback to an API key or another model.
- Retrying model calls.
- Images or other non-text content in the model view: nothing sends any today.
- Changing the owner's `.env`. The owner does this by hand.

## Further Notes

- Measured on 2026-10-25 (Claude Code 2.1.310, Pro login). Without `--safe-mode`, an otherwise isolated call still carried about 55k tokens of the owner's setup; with it, about 1k. Calls took 1.4–8 s. `sonnet` and `claude-sonnet-5-5` both resolved to `claude-sonnet-5-5`, and `sonet` was refused.
- `claude_code:claude-opus-5-5` works on the Pro login, so the judge can move to the subscription too.
- The exact usage-limit result hasn't been seen yet. Capture it the first time it happens and pin it in the stand-in's scripted results.
- The wrapper depends on the CLI's flags and its JSON result shape. Recheck both when Claude Code updates. The live test is the alarm.
- Manual steps for the owner once this ships: set `MODEL_NAME=claude_code:claude-sonnet-5-5` and `EVAL_JUDGE_MODEL=claude_code:claude-opus-5-5`, and replace `GOOGLE_API_KEY` with a key from a project with billing turned off.
- Records from this session: ADR-016, and an amendment to ADR-009.
