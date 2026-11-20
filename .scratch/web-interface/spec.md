# Spec: Web interface beside the CLI

Status: ready-for-agent

Source: the grilling session of 2026-11-19 (Q1–Q12). Vocabulary follows `GLOSSARY.md` (Conversation, Follow-up, Approval, Write action, Outbound read, Fixture world). The decision record is ADR-018, which supersedes ADR-008. Decisions also respect ADR-010 (classification fails closed), ADR-011 (the Fixture world is the only test target), ADR-016 (Claude Code model, `--resume`) and ADR-017 (Outbound reads).

## Problem Statement

The CLI is the only way to use the agent. One terminal holds one Conversation. A second Conversation needs a second terminal, and the only way back to an earlier Conversation is its id, printed at start and exit, or a bare `--resume` for the most recent. During a turn the CLI shows nothing until the answer or the Approval box, and a multi-tool question can take a minute or more. The app will later go online, so whatever interface comes next needs a login.

## Solution

A web server, `python -m agent.web`, serves a React app on localhost. The owner logs in with a password. They see every real Conversation, CLI-started ones included, can open any of them, start new ones, and keep several running at once. A turn shows its tool calls live as they happen. An Approval is a card with Approve and Reject buttons, and a Follow-up rejects it as in the CLI. A Stop button cancels a running turn. A status strip shows whether each integration's login is alive, and names the command to fix one that isn't.

The web interface and the CLI are two front ends on the same Conversations: either can continue a Conversation the other started. Both write a Conversation's run log entry after every turn.

## User Stories

1. As the owner, I want to start the web interface with one command, so that using it is as easy as the CLI.
2. As the owner, I want to log in with a password, so that no other web page or person can use my agent.
3. As the owner, I want to stay logged in for a week on my browser, so that I'm not asked every time.
4. As the owner, I want to log out, so that I can end access on a browser.
5. As the owner, I want repeated wrong passwords slowed down, so that guessing doesn't work.
6. As the owner, I want requests from other web pages refused even while I'm logged in, so that a malicious page can't approve a Write action or read my data through my browser.
7. As the owner, I want a list of all my real Conversations, newest activity first, each titled by its first question, so that I can find one again without its id.
8. As the owner, I want Conversations I started in the CLI in that list, so that I can continue them in the browser.
9. As the owner, I want a Conversation started in the browser to be `--resume`able in the CLI, so that I can switch front ends.
10. As the owner, I want to open a Conversation and see its earlier questions and answers, so that I know where I left off.
11. As the owner, I want to start a new Conversation, so that I can ask about something unrelated.
12. As the owner, I want to ask Follow-ups in a Conversation, so that the agent answers with everything said earlier.
13. As the owner, I want several Conversations running at once, so that a slow question doesn't block another.
14. As the owner, I want to see each tool call as it starts and when it finishes or fails, so that I know the agent is working and what it's doing.
15. As the owner, I want a tool call's arguments and result folded away but expandable, so that the answer stays readable and I can still check the agent's work.
16. As the owner, I want answers rendered as Markdown, so that lists and tables read well.
17. As the owner, I want HTML inside answers (from quoted emails) never to run, so that an email can't act in the page that holds my login.
18. As the owner, I want an Approval shown as one card listing every proposed Write action and gated Outbound read, so that I approve or reject them together, as in the CLI.
19. As the owner, I want sending a Follow-up while an Approval waits to reject it, so that the web interface behaves like the CLI and the glossary.
20. As the owner, I want a Stop button for a running turn, so that I can cancel a question that is going wrong, as Ctrl-C does.
21. As the owner, I want a Conversation open in two tabs to show the same live state in both, so that neither tab shows a stale Approval.
22. As the owner, I want only one turn at a time per Conversation, so that two tabs can't send conflicting questions or answers.
23. As the owner, I want to answer an Approval from either tab, and have the other tab update, so that it doesn't matter which one I use.
24. As the owner, I want the server to refuse to start with a dead Google or Claude Code login, naming the command, as the CLI does.
25. As the owner, I want a status strip showing each integration's login, so that I see a dead login before a question fails.
26. As the owner, I want a dead login to name its login command, so that I know how to fix it.
27. As the owner, I want a fresh login picked up on the next turn without restarting the server, so that a server left running for days keeps working after I log in again.
28. As the owner, I want every Conversation, web or CLI, in memory as soon as a turn ends, so that a crash or a tab left open never loses it from recall.
29. As the owner, I want each Conversation to be one Langfuse trace, shared with the CLI, so that a Conversation is traced the same way from either front end.
30. As the owner, I want to set or change the password with one command, so that the hash never has to be made by hand.
31. As the maintainer, I want the web server tested against the Fixture world with a stand-in model, so that tests never touch real data or my subscription.
32. As the maintainer, I want a few browser tests for the main journeys, so that UI bugs like a stale Approval card are caught.
33. As the maintainer, I want the CLI and the web server to drive Conversations through the same driver, so that Approval, abandonment and cancellation rules can't drift apart.

## Implementation Decisions

### Server and app

- A new package `src/agent/web/` holds the FastAPI app. `python -m agent.web` starts it with uvicorn on `127.0.0.1:<WEB_PORT>` (default `8000`). The bind host is a setting with the default `127.0.0.1`, kept for the later online deployment.
- The React app (Vite, TypeScript) lives in a top-level `web/` folder. FastAPI serves its built files from `web/dist`. During development, Vite's dev server proxies API and event requests to FastAPI. A missing build is a clear startup message naming the build command, not a crash.
- Real data only. There is no `--fixtures` flag. The app is built by a factory that takes the graph, tools, model and checkpoint path, so tests inject Fixture-world tools and the stand-in model (ADR-011).
- Startup does what the CLI's startup does, in the same order: build the model, check Langfuse (untraced with a warning if it's down), check the Google login and (for a `claude_code:` agent or judge model) the Claude Code login, stopping with the same messages, then load tools, printing notices for skipped MCP servers. Shared startup steps move out of `cli.py` into a module both front ends call, so the messages stay identical.
- One `AsyncSqliteSaver` on `checkpoint_db(fixtures=False)` and one compiled graph serve every Conversation for the server's lifetime.

### Login

- One owner account. The password is stored only as an argon2id hash in `.env` as `WEB_PASSWORD_HASH` (a new optional setting in `config.py`). `python -m agent.web.set_password` reads the password twice without echo and writes or replaces the line in `.env`. The setup wizard gains a step that runs it. The server refuses to start without a hash, naming that command.
- Logging in sets a signed session cookie: `HttpOnly`, `SameSite=Strict`, `Secure` unless the host is localhost, valid 7 days. The signing key is derived from the password hash, so changing the password ends every session. Logout clears the cookie.
- Failed logins are rate-limited in memory (for example, 5 failures per minute per client, then refused until the window passes).
- Every request, the event streams included, is refused unless `Host` is `localhost:<port>` or `127.0.0.1:<port>`. Every state-changing request and event stream is refused unless `Origin` is the app's own. An event stream is known by its route (`/api/conversations/{id}/events`), not by its `Accept` header. A browser may leave `Origin` off a same-origin `EventSource` GET, so a GET (or HEAD/OPTIONS) to an event stream with no `Origin` is accepted when `Sec-Fetch-Site: same-origin` says the app itself opened it; a foreign `Origin` is still refused, and state-changing requests always need `Origin`. No CORS headers are sent. Every endpoint except login and the static login page needs a valid session.

### Conversations

- **The list** reads the real checkpoint file: one row per thread, titled by its first `HumanMessage` (cut to about 80 characters), with the time of its latest checkpoint, newest first. No rename and no delete. Listing must stay fast with hundreds of threads. If listing through `alist` is too slow, query the checkpoint table for each thread's latest checkpoint directly.
- **Opening** a Conversation shows its questions, answers, tool steps and any pending Approval, rebuilt from the checkpoint.
- **Starting** a Conversation creates a new thread id (uuid4), as the CLI does. The first question is sent with it.
- **Turns** go through `run_conversation` and `close_interrupted_turn` in `src/agent/conversation.py`, the same driver as the CLI, so Follow-up-as-rejection and closing a cancelled turn behave identically. To show steps live, the driver gains a streaming form, or the web server uses `astream` with the same inputs. The CLI keeps its current behaviour.
- **One turn at a time per Conversation:** the server holds one per-thread state (idle, running, or waiting for an Approval) and an asyncio lock. A question or decision sent while a turn runs is refused with a clear error, and the app disables input meanwhile. An Approval decision is accepted only while that thread is waiting for one. It carries the id of the interrupt it answers, and is refused if that id is no longer the pending one, so a stale tab can't resume a checkpoint that has moved on.
- **Parallel across Conversations:** turns on different threads run concurrently. Each MCP tool call opens its own session (`mcp_loader.py`), so the shared tools are safe.
- **Stop** cancels that thread's running turn task and runs `close_interrupted_turn`, as Ctrl-C does in the CLI.
- **Known failures** (a `ClaudeCodeError`, the step limit) end the turn with the same message the CLI prints. Other exceptions end the turn with an error shown in the Conversation, and the server keeps running.
- The CLI and the web server on the same Conversation at the same moment are not guarded (ADR-018).

### Live events

- One Server-Sent Events stream per open Conversation view, multiplexed so every tab on a thread gets the same events: the turn started, a tool call started (name, arguments), a tool call finished or failed (result, error), an Approval is pending (the same message, actions and interrupt id the CLI shows), the answer, the turn stopped (cancelled, known failure, error), and login status. A tab that connects mid-turn first gets the current state, then live events.
- The answer arrives whole. The `claude_code:` model can't stream text.

### Rendering

- Answers are rendered as Markdown with raw HTML disabled (e.g. `react-markdown` without `rehype-raw`). Tool arguments and results are shown as escaped text in a collapsed detail.

### Approval

- One card per pending interrupt, listing every proposed Write action and gated Outbound read, from the same interrupt payload `human_review_node` produces. It has Approve and Reject buttons. The message box stays usable: sending a Follow-up rejects the pending Approval through the driver, as in the CLI.

### Login status

- A status strip shows Google, Claude Code (when a `claude_code:` model is configured), MS365 and Informer, each alive or dead. A dead one names its login command (`python -m agent.auth.google`, `claude auth login`, the MS365 or Informer login).
- The checks re-run at the start of every turn, without blocking it for long: a cached result, refreshed in the background with a short timeout.
- After a re-login: Google is already picked up per call (the tools read `credentials/token.json` each time). An MCP server skipped at startup for a login problem is loaded again on the next turn after its check passes, and the server rebuilds the graph's bound tools for later turns. A turn already running keeps its tools.

### Run log after every turn

- Both front ends write the Conversation's run log entry when a turn ends: answered, parked at an Approval, cancelled, or stopped by a known failure or error. The entry is built from the whole thread, as today, and replaces the thread's earlier entry (`episodic.py` deletes by thread id). Errors from earlier turns stay in the entry. The CLI's exit write stays as a final pass, so a crash between turns still logs.
- The questions list (`user_input`) is rebuilt from the thread's `HumanMessage`s each time, not collected in memory, so a web turn and a CLI turn on the same Conversation both see every question.
- Known failures must survive across front ends and restarts. Store them with the Conversation, in the thread state or read back from the existing run log entry, not only in a process-local list.

### Tracing

- One Langfuse callback handler per Conversation, with the trace id derived from the thread id exactly as `cli.py` does (`thread_id.replace("-", "")`), `trace_name="web-run"`, the same `user_id` and the prompt-version metadata.

## Testing Decisions

- All server tests run on the Fixture world with the stand-in model and Fixture tools injected through the app factory (ADR-011). No live model calls, consistent with the owner's quota rule.
- pytest with FastAPI's test client (and `httpx.AsyncClient` for SSE) covers: refusing to start without a password hash; login success and failure; the rate limit; cookie flags and expiry; sessions ended by a password change; `Host` and `Origin` refusals; unauthenticated refusals; the list (CLI-started threads included, titles, order); opening a thread with a pending Approval; a turn with tool steps emitted in order; one turn at a time (a second question refused); a stale interrupt id refused; Approve, Reject, and Follow-up as rejection; Stop closing open tool calls; known failures ending the turn without stopping the server; two parallel Conversations; two SSE clients on one thread receiving the same events; the run log entry rewritten after each turn; login status flipping and a skipped MCP server loaded again after its login passes.
- The CLI's existing tests keep passing. New CLI tests cover the per-turn run log write.
- Playwright (Python, `pytest-playwright`) runs a few journeys against the built app on a Fixture-backed server: log in; start a Conversation and see a tool step then the answer; approve a Write action; two tabs on one Conversation, where answering in one updates the other and disables its card. Browser tests are marked so `uv run pytest` can skip them when no browser is installed.
- No JavaScript unit-test stack (no Vitest).

## Out of Scope

- The Fixture world in the web interface.
- Sign in with Google, passkeys, more than one account, and deploying online (a later feature replaces the password with Google sign-in, per ADR-018).
- Logging in to Google, MS365 or Claude Code from the browser.
- Renaming, deleting or searching Conversations.
- Guarding the CLI and the web server against driving the same Conversation at the same moment.
- Streaming answer text word by word.
- Uploading files through the browser.

## Further Notes

- Until Sign in with Google replaces the password, the bind host must stay `127.0.0.1`. The setting exists for the deployment feature, not for exposing the app on a LAN.
- `CLAUDE.md` gains the web run command, the build command and the `WEB_*` settings. Its CLI description changes from "logged at exit" to "logged after every turn".
