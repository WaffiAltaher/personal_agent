"""
cli.py — Entry point with Langfuse tracing wired in.

``python -m agent.cli [--fixtures] [--debug] ["first question"]`` starts a session: the agent
starts once, answers the question if one was given, then reads Follow-ups at a ``> `` prompt,
all on one Conversation (one thread, one Langfuse trace). An empty line does nothing; ``exit``,
``quit`` or Ctrl-D ends the session. At exit the whole Conversation is one run log entry.
Ctrl-C while a turn runs cancels that turn and returns to ``> ``; at a prompt it clears the line.

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

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langfuse import propagate_attributes
from langgraph.errors import GraphRecursionError
from agent.auth.claude_code import ClaudeCodeLoginCheckTimeout, ClaudeCodeLoginRequired, check_claude_code_login
from agent.auth.google import GoogleLoginRequired, check_google_login
from agent.chat_model import ModelConfigError, create_chat_model, is_claude_code_model
from agent.claude_code_model import ClaudeCodeError
from agent.conversation import close_interrupted_turn, run_conversation
from agent.graph import build_graph, get_checkpointer, log_run_to_memory
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

    usage = "Usage: python -m agent.cli [--debug] [--fixtures] ['<your first question>']"
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


EXIT_WORDS = ("exit", "quit")


def _read_line(prompt: str) -> str:
    """Read one line at the session prompt; raises EOFError on Ctrl-D. Tests replace this."""
    return input(prompt)


_turn: asyncio.Task | None = None  # the graph call Ctrl-C cancels, while one runs


def _on_sigint(signum, frame) -> None:
    """Ctrl-C: cancel the running graph call; otherwise interrupt the prompt's read."""
    if _turn is not None and not _turn.done():
        _turn.cancel()
        _turn.get_loop().call_soon_threadsafe(lambda: None)  # wake the loop if it is waiting
        return
    raise KeyboardInterrupt


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
    print("=" * 60)


def _prompt_decision() -> str:
    """Prompt the user until they type 'approve' or 'reject'."""
    while True:
        try:
            decision = _read_line("Your decision: ").strip().lower()
        except KeyboardInterrupt:
            print()  # Ctrl-C only clears the line
            continue
        except EOFError:
            print("\nAborted.")
            sys.exit(0)
        if decision in ("approve", "reject"):
            return decision
        print("Please type 'approve' or 'reject'.")


async def main():
    debug, fixtures, user_input = _parse_args(sys.argv[1:])

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
    # The checkpointer uses this to namespace the checkpoint.
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
    result: dict = {"messages": []}
    run_error: str | None = None
    questions: list[str] = []
    previous_sigint = signal.signal(signal.SIGINT, _on_sigint)

    try:
        with memory_ctx:
            async with get_checkpointer() as checkpointer:
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

                with propagate_attributes(
                    user_id="waffi",
                    trace_name="cli-run",
                    metadata={"prompt-version": settings.prompt_version},
                ):
                    first = [user_input] if user_input is not None else []
                    while True:
                        if first:
                            line = first.pop()
                        else:
                            try:
                                line = _read_line("> ")
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
                        turn_start = len(result["messages"])

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
                                print(f"\nResuming with: {decision}\n")

                                turn = await _cancellable(run_conversation(
                                    agent_graph,
                                    config,
                                    tools=tools,
                                    resume_decision=decision,
                                ))
                        except asyncio.CancelledError:
                            if asyncio.current_task().cancelling():
                                raise  # the session itself is being cancelled, not just the turn
                            # Ctrl-C: tool calls the cancel left open get answered before the next question.
                            await close_interrupted_turn(agent_graph, config)
                            print("\nInterrupted.")
                            continue
                        result = turn

                        last = result["messages"][-1]
                        print(_stringify_content(last.content))

                        if debug:
                            # Only what this turn added: earlier turns were shown after their own turn.
                            _display_debug_trace({**result, "messages": result["messages"][turn_start:]})

        # A Fixture-world run is about seeded stand-in data, not the owner's: keep it out of real memory.
        # The whole Conversation is one run log entry; a session with no question leaves none.
        if not fixtures and questions:
            log_run_to_memory(result, "\n".join(questions), model_name=settings.model_name)
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        if not fixtures and questions:
            log_run_to_memory(
                result,
                "\n".join(questions),
                model_name=settings.model_name,
                error=run_error,
            )
        # A Claude Code call that couldn't produce a turn already says what to do (ADR-016).
        if isinstance(exc, ClaudeCodeError):
            print(f"Stopped: {exc}")
            sys.exit(1)
        raise
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        print(f"Conversation {thread_id}")
        flush_traces()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except GraphRecursionError:
        print("Stopped: the agent hit its step limit (~10 tool rounds) without a final answer. "
              "Try a narrower question.")
        sys.exit(1)
    except ModelConfigError as exc:
        print(f"Cannot start: {exc}")
        sys.exit(1)