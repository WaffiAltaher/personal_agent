"""
cli.py — Entry point with Langfuse tracing wired in.

``python -m agent.cli [--fixtures] [--debug] [--resume [<id>]] ["first question"]`` starts a session (one CLI process): the agent
starts once, answers the question if one was given, then reads Follow-ups at a ``> `` prompt,
all on one Conversation (one thread, one Langfuse trace). An empty line does nothing; ``exit``,
``quit`` or Ctrl-D ends the session. The whole Conversation is one run log entry, written after
every turn (and once more at exit), so it exists while the session is still open.
``--resume <id>`` continues that Conversation from an earlier session; a bare ``--resume`` the
most recent one. Real and ``--fixtures`` runs keep their Conversations in separate checkpoint files.
Ctrl-C while a turn runs cancels that turn and returns to ``> ``; at a prompt it clears the line;
anywhere else (between turns, while a cancelled turn is closed) it ends the session.

Real-mode runs check the Google login before the agent starts. If Gmail or Calendar
would need a new browser login, startup stops and names ``python -m agent.auth.google``.
With a ``claude_code:`` agent or judge model they also check the Claude Code login, and stop
naming ``claude auth login`` unless it is a claude.ai login.
Use ``--fixtures`` for the seeded Fixture world (no Google login check).
"""

import asyncio
import signal
import sys
import uuid
from contextlib import nullcontext
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langfuse import propagate_attributes
from langgraph.errors import GraphRecursionError
from agent.auth.claude_code import ClaudeCodeLoginCheckTimeout, ClaudeCodeLoginRequired, check_claude_code_login
from agent.auth.google import GoogleLoginRequired, check_google_login
from agent.chat_model import ModelConfigError, create_chat_model, is_claude_code_model
from agent.claude_code_model import ClaudeCodeError
from agent.conversation import close_interrupted_turn, run_conversation
from agent.graph import build_graph, checkpoint_db, get_checkpointer, log_run_to_memory
from agent.memory import fixtures_semantic_memory
from agent.tracing import flush_traces, get_callback_handler, verify_connection
from agent.config import settings
from agent.tools import load_all_tools
from fixture_world import clock


def _parse_args(argv: list[str]) -> tuple[bool, bool, str | None]:
    """Parse minimal CLI flags without adding a full CLI framework yet."""
    debug = False
    args = list(argv)
    if "--debug" in args:
        debug = True
        args.remove("--debug")

    # --fixtures: MCP tools come from the Fixture world (seeded stand-ins), not real ITtopia data.
    fixtures = False
    if "--fixtures" in args:
        fixtures = True
        args.remove("--fixtures")

    usage = "Usage: python -m agent.cli [--debug] [--fixtures] [--resume [<id>]] ['<your first question>']"
    # A mistyped flag (--fixture) must not become the question: it would run against real data.
    unknown = [a for a in args if a.startswith("--")]
    if unknown:
        print(f"Unknown option: {' '.join(unknown)}\n{usage}")
        sys.exit(1)
    # No question: the session goes straight to the `> ` prompt.
    if not args:
        return debug, fixtures, None

    # An unquoted question arrives as several words: it is the whole line, not its first word.
    return debug, fixtures, " ".join(args)


def _pop_resume(argv: list[str]) -> tuple[bool, str | None, list[str]]:
    """Take ``--resume [<id>]`` out of argv. The word after it is the id only if it is a
    Conversation id (a UUID); otherwise it is the question and the resume is bare."""
    args = list(argv)
    if "--resume" not in args:
        return False, None, args
    at = args.index("--resume")
    args.pop(at)
    if at < len(args):
        try:
            return True, str(uuid.UUID(args[at])), args[:at] + args[at + 1:]
        except ValueError:
            pass
    return True, None, args


async def _resumed_thread_id(db_path: str, thread_id: str | None) -> str | None:
    """The thread to resume from this world's checkpoint file: the given one if it is there,
    else the most recent. None if there is no such Conversation."""
    async with get_checkpointer(db_path) as checkpointer:
        if thread_id is not None:
            found = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
            return thread_id if found else None
        async for latest in checkpointer.alist(None, limit=1):
            return latest.config["configurable"]["thread_id"]
        return None


EXIT_WORDS = ("exit", "quit")

STEP_LIMIT_STOPPED = ("Stopped: the agent hit its step limit (~10 tool rounds) without a final answer. "
                      "Try a narrower question.")


def _read_line(prompt: str) -> str:
    """Read one line at the session prompt; raises EOFError on Ctrl-D. Tests replace this."""
    return input(prompt)


_turn: asyncio.Task | None = None  # the graph call Ctrl-C cancels, while one runs
_session: asyncio.Task | None = None  # the session Ctrl-C ends, outside a turn and a prompt
_reading = False  # a prompt is waiting for a line
_ending = False  # Ctrl-C asked the session to end


def _on_sigint(signum, frame) -> None:
    """Ctrl-C: cancel the running graph call; at a prompt interrupt its read; anywhere else end
    the session by cancelling it, so its exit path still runs (raising here could escape it)."""
    global _ending
    if _turn is not None and not _turn.done():
        _turn.cancel()
        _turn.get_loop().call_soon_threadsafe(lambda: None)  # wake the loop if it is waiting
        return
    if _reading:
        raise KeyboardInterrupt
    if _ending or _session is None:
        return  # the session is already ending: let it write its run log entry
    _ending = True
    _session.cancel()
    _session.get_loop().call_soon_threadsafe(lambda: None)


def _read(prompt: str) -> str:
    """Read a line at a prompt, where Ctrl-C only clears the line. Ctrl-C that came while no
    prompt was shown ends the session: the read answers EOF, as Ctrl-D would."""
    global _reading
    if _ending:
        raise EOFError
    _reading = True
    try:
        return _read_line(prompt)
    finally:
        _reading = False


async def _cancellable(coro):
    """Run one graph call so Ctrl-C can cancel it (raises CancelledError when it does)."""
    global _turn
    _turn = asyncio.ensure_future(coro)
    try:
        return await _turn
    finally:
        _turn = None


def _stringify_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


def _display_debug_trace(result: dict) -> None:
    """Print the message trajectory and captured structured errors."""
    print("\n" + "=" * 60)
    print("DEBUG: MESSAGE TRAJECTORY")
    print("=" * 60)

    for idx, message in enumerate(result.get("messages", []), start=1):
        print(f"\n[{idx}] {type(message).__name__}")

        content = _stringify_content(getattr(message, "content", ""))
        if content:
            print(f"content: {content[:1000]}")
        else:
            print("content: <empty>")

        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", [])
            if tool_calls:
                print("tool_calls:")
                for tool_call in tool_calls:
                    print(f"  - {tool_call['name']}({tool_call.get('args', {})}) id={tool_call['id']}")

            invalid_tool_calls = getattr(message, "invalid_tool_calls", [])
            if invalid_tool_calls:
                print("invalid_tool_calls:")
                for tool_call in invalid_tool_calls:
                    print(f"  - {tool_call}")

            finish_reason = getattr(message, "response_metadata", {}).get("finish_reason")
            if finish_reason:
                print(f"finish_reason: {finish_reason}")

        if isinstance(message, ToolMessage):
            print(f"tool_call_id: {message.tool_call_id}")

    errors = result.get("errors", [])
    if errors:
        print("\n" + "=" * 60)
        print("DEBUG: STRUCTURED ERRORS")
        print("=" * 60)
        for error in errors:
            print(
                f"- node={error.get('node')} tool={error.get('tool')} "
                f"type={error.get('exception_type')} message={error.get('message')}"
            )
            if error.get("args") is not None:
                print(f"  args={error['args']}")


def _display_interrupt(interrupt_payload: dict) -> None:
    """Pretty-print the interrupt payload to the terminal."""
    print("\n" + "=" * 60)
    print("⚠️  AGENT ACTION REQUIRES YOUR APPROVAL")
    print("=" * 60)
    print(interrupt_payload.get("message", ""))
    print()
    print(interrupt_payload.get("actions", ""))
    print()
    print(interrupt_payload.get("instructions", "Type 'approve' or 'reject'."))
    print("Or type a follow-up question: it rejects these actions and is answered instead.")
    print("=" * 60)


@dataclass(frozen=True)
class Decision:
    """What the owner answered at the Approval prompt."""
    kind: str  # "approve" | "reject" | "follow-up" | "end" (Ctrl-D: the session ends)
    follow_up: str = ""


def _prompt_decision() -> Decision:
    """Prompt until the owner types 'approve' or 'reject', or a Follow-up (more than one word), or Ctrl-D."""
    while True:
        try:
            line = _read("Your decision: ").strip()
        except KeyboardInterrupt:
            print()  # Ctrl-C only clears the line
            continue
        except EOFError:
            print("\nAborted.")
            return Decision("end")
        if line.lower() in ("approve", "reject"):
            return Decision(line.lower())
        if len(line.split()) > 1:
            return Decision("follow-up", line)
        print("Please type 'approve' or 'reject', or ask a follow-up question.")


async def main():
    resume, resume_id, argv = _pop_resume(sys.argv[1:])
    debug, fixtures, user_input = _parse_args(argv)

    # Build the chat model first: a missing API key for the selected provider
    # stops the run here, before any MCP server is started.
    model = create_chat_model()

    # Verify Langfuse is reachable before we do any work. If it isn't, say which address
    # was tried and run untraced: observability failing shouldn't block the agent.
    langfuse_connected = verify_connection()
    if not langfuse_connected:
        print(f"Warning: Langfuse connection failed at {settings.langfuse_base_url}. "
              "Traces will not be recorded.")

    if not fixtures:
        try:
            check_google_login()
        except GoogleLoginRequired as exc:
            print(f"Cannot start: {exc}")
            sys.exit(1)
        except FileNotFoundError as exc:
            print(f"Cannot start: {exc}")
            sys.exit(1)
        # A claude_code: agent or judge model runs on the Claude Code login; check it the same way.
        if any(is_claude_code_model(m) for m in (settings.model_name, settings.eval_judge_model)):
            try:
                check_claude_code_login(settings.claude_code_binary)
            except (ClaudeCodeLoginRequired, ClaudeCodeLoginCheckTimeout, FileNotFoundError) as exc:
                print(f"Cannot start: {exc}")
                sys.exit(1)

    # Each CLI session gets a fresh thread_id: one Conversation, independent of other sessions.
    # The checkpointer uses this to namespace the checkpoint. --resume reuses an earlier one.
    db_path = checkpoint_db(fixtures)
    if resume:
        resumed = await _resumed_thread_id(db_path, resume_id)
        if resumed is None:
            world = "the Fixture world" if fixtures else "real data"
            print(f"Cannot resume: no Conversation {resume_id} in {world}." if resume_id
                  else f"Cannot resume: there is no Conversation in {world} yet.")
            sys.exit(1)
        thread_id = resumed
    else:
        thread_id = str(uuid.uuid4())
    print(f"Conversation {thread_id}")

    # Langfuse v4 (OTel-based) requires a 32 lowercase hex char trace ID — no dashes.
    # We derive it from thread_id so the two IDs stay linked.
    langfuse_trace_id = thread_id.replace("-", "")

    # One handler per session = one trace in Langfuse for the whole Conversation. With Langfuse down there is no handler: the run is untraced.
    callbacks = [get_callback_handler(trace_id=langfuse_trace_id)] if langfuse_connected else []

    config = {
        "callbacks": callbacks,
        "configurable": {"thread_id": thread_id},
        # Backstop only: settings.max_iterations bounds model calls; keep headroom above that.
        "recursion_limit": max(settings.max_iterations * 5 + 10, 40),
    }

    # Against the Fixture world, "today" is its pinned date, for the model and the stand-ins alike.
    today = clock.pin_today() if fixtures else None
    memory_ctx = fixtures_semantic_memory() if fixtures else nullcontext()
    run_error: str | None = None
    questions: list[str] = []
    unlogged_failures: list[str] = []  # known failures not yet in the entry; it keeps the ones it holds

    async def log_turn() -> None:
        # A Fixture-world run is about seeded stand-in data, not the owner's: keep it out of real memory.
        if not fixtures:
            await write_run_log(db_path, thread_id, error="; ".join(unlogged_failures) or None, questions=questions)
            unlogged_failures.clear()
    global _session, _ending
    _session, _ending = asyncio.current_task(), False
    previous_sigint = signal.signal(signal.SIGINT, _on_sigint)

    try:
        with memory_ctx:
            async with get_checkpointer(db_path) as checkpointer:
                tools, notices = await load_all_tools(fixtures=fixtures)
                if fixtures:
                    print(
                        f"Running against the Fixture world (seeded MS365 stand-in and fake Informer API), "
                        f"today {today}."
                    )
                # An unavailable integration doesn't stop the run; say which one and why.
                for notice in notices:
                    print(f"Notice: {notice}")
                agent_graph = build_graph(checkpointer, tools, model, today=today)
                if resume:
                    # The run log entry covers the whole Conversation, earlier sessions included.
                    questions = [
                        _stringify_content(m.content)
                        for m in (await agent_graph.aget_state(config)).values.get("messages", [])
                        if isinstance(m, HumanMessage)
                    ]

                with propagate_attributes(
                    user_id="waffi",
                    trace_name="cli-run",
                    metadata={"prompt-version": settings.prompt_version},
                ):
                    pending_questions = [user_input] if user_input is not None else []
                    moved_on = False  # the last turn left its Approval for a Follow-up
                    while True:
                        if pending_questions:
                            line = pending_questions.pop()
                        else:
                            try:
                                line = _read("> ")
                            except EOFError:
                                print()
                                break
                            except KeyboardInterrupt:
                                print()  # Ctrl-C only clears the line
                                continue
                        question = line.strip()
                        if not question:
                            continue
                        if question.lower() in EXIT_WORDS:
                            break
                        questions.append(question)
                        # --debug shows what the thread gained since this turn started; a turn that
                        # moved on from its Approval is shown with the Follow-up that answered it.
                        if not moved_on:
                            turn_start = len((await agent_graph.aget_state(config)).values.get("messages", []))
                        moved_on = False

                        # A known failure ends the turn, not the session: the thread still ends on
                        # answered messages (these are raised before a node writes anything).
                        try:
                            turn = await _cancellable(run_conversation(
                                agent_graph,
                                config,
                                tools=tools,
                                user_message=question,
                                today=today,
                            ))
                            # HITL loop — handle zero or more interrupts per turn.
                            while "__interrupt__" in turn:
                                for interrupt_obj in turn["__interrupt__"]:
                                    _display_interrupt(interrupt_obj.value)

                                decision = _prompt_decision()
                                if decision.kind in ("follow-up", "end"):
                                    break
                                print(f"\nResuming with: {decision.kind}\n")

                                turn = await _cancellable(run_conversation(
                                    agent_graph,
                                    config,
                                    tools=tools,
                                    resume_decision=decision.kind,
                                ))
                        except asyncio.CancelledError:
                            if asyncio.current_task().cancelling():
                                raise  # the session itself is being cancelled, not just the turn
                            # Ctrl-C: tool calls the cancel left open get answered before the next question.
                            await close_interrupted_turn(agent_graph, config)
                            print("\nInterrupted.")
                            await log_turn()
                            continue
                        except ClaudeCodeError as exc:
                            # A Claude Code call that couldn't produce a turn already says what to do (ADR-016).
                            print(f"Stopped: {exc}")
                            unlogged_failures.append(f"{type(exc).__name__}: {exc}")
                            await log_turn()
                            continue
                        except GraphRecursionError as exc:
                            print(STEP_LIMIT_STOPPED)
                            unlogged_failures.append(f"{type(exc).__name__}: {exc}")
                            await log_turn()
                            continue

                        await log_turn()
                        if "__interrupt__" in turn:
                            if decision.kind == "end":
                                break  # Ctrl-D at the Approval prompt ends the session
                            # A Follow-up rejects the pending Write actions; the loop answers it as the next turn.
                            pending_questions.append(decision.follow_up)
                            moved_on = True
                            continue

                        last = turn["messages"][-1]
                        print(_stringify_content(last.content))

                        if debug:
                            # Only what this turn added: earlier turns were shown after their own turn.
                            _display_debug_trace({**turn, "messages": turn["messages"][turn_start:]})
    except asyncio.CancelledError:
        if not _ending:
            raise
        print("\nInterrupted.")  # Ctrl-C outside a turn ended the session
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        # The session ends: name the command that resumes the Conversation, in the same world.
        resume_cmd = f"python -m agent.cli {'--fixtures ' if fixtures else ''}--resume {thread_id}"
        print(f"Conversation ended by an error. Resume it with: {resume_cmd}")
        raise
    finally:
        if _ending:
            asyncio.current_task().uncancel()  # Ctrl-C's cancel must not stop this exit path
        # The entry is written after every turn; this last pass adds a crash or a cancel outside a turn.
        if run_error:
            unlogged_failures.append(run_error)
        await log_turn()
        signal.signal(signal.SIGINT, previous_sigint)
        _session = None
        print(f"Conversation {thread_id}")
        flush_traces()


async def _conversation_so_far(db_path: str, config: dict) -> dict:
    """The Conversation's thread as last checkpointed, for its run log entry. No messages if it
    can't be read: the error that ended the session is the one to show."""
    try:
        async with get_checkpointer(db_path) as checkpointer:
            saved = await checkpointer.aget_tuple(config)
        return {"messages": [], **(saved.checkpoint["channel_values"] if saved else {})}
    except Exception:
        return {"messages": []}


async def write_run_log(db_path: str, thread_id: str, *, error: str | None = None,
                        questions: list[str] = ()) -> None:
    """Write the Conversation's run log entry from its thread in the checkpoint file at ``db_path``,
    replacing the thread's earlier entry. The questions are the thread's HumanMessages; ``questions``
    stands in only while the thread has none (a first turn that failed before checkpointing). ``error``
    is a failure not yet in the entry: the entry keeps the ones it already holds. Writes nothing for a
    thread with no question and no error."""
    result = await _conversation_so_far(db_path, {"configurable": {"thread_id": thread_id}})
    asked = [_stringify_content(m.content) for m in result["messages"] if isinstance(m, HumanMessage)]
    asked = asked or list(questions)
    if not asked and not error:
        return
    log_run_to_memory(result, "\n".join(asked), model_name=settings.model_name, error=error, thread_id=thread_id)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except GraphRecursionError:
        print(STEP_LIMIT_STOPPED)
        sys.exit(1)
    except ModelConfigError as exc:
        print(f"Cannot start: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print()  # Ctrl-C before the session could start: nothing to log, no traceback
        sys.exit(130)