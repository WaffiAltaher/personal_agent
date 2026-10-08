"""
cli.py — Entry point with Langfuse tracing wired in.
"""

import asyncio
import sys
import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langfuse import propagate_attributes
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from agent.chat_model import ModelConfigError, create_chat_model
from agent.graph import build_graph, get_checkpointer, log_run_to_memory
from agent.tracing import flush_traces, get_callback_handler, verify_connection
from agent.config import settings
from agent.tools import load_all_tools
from fixture_world import clock


def _parse_args(argv: list[str]) -> tuple[bool, bool, str]:
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

    if not args:
        print("Usage: python -m agent.cli [--debug] [--fixtures] '<your question>'")
        sys.exit(1)

    return debug, fixtures, args[0]


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
            decision = input("Your decision: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
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

    # Verify Langfuse is reachable before we do any work.
    # This fails loudly rather than running the agent and silently losing traces.
    if not verify_connection():
        print("Warning: Langfuse connection failed. Traces will not be recorded.")
        # We continue anyway — observability failing shouldn't block the agent.

    # Each CLI run gets a fresh thread_id so runs are independent.
    # The checkpointer uses this to namespace the checkpoint.
    thread_id = str(uuid.uuid4())

    # Langfuse v4 (OTel-based) requires a 32 lowercase hex char trace ID — no dashes.
    # We derive it from thread_id so the two IDs stay linked.
    langfuse_trace_id = thread_id.replace("-", "")

    # One handler per run = one trace in Langfuse.
    langfuse_handler = get_callback_handler(trace_id=langfuse_trace_id)

    config = {
        "callbacks": [langfuse_handler],
        "configurable": {"thread_id": thread_id},
        # One tool round is 4 super-steps (budget → agent → human_review → tools),
        # so 40 caps a run at ~10 tool rounds instead of LangGraph's default 10,007.
        "recursion_limit": 40,
    }

    # Against the Fixture world, "today" is its pinned date, for the model and the stand-ins alike.
    today = clock.pin_today() if fixtures else None

    async with get_checkpointer() as checkpointer:
        tools, notices = await load_all_tools(fixtures=fixtures)
        if fixtures:
            print(f"Running against the Fixture world (seeded MS365 stand-in and fake Informer API), today {today}.")
        # An unavailable integration doesn't stop the run; say which one and why.
        for notice in notices:
            print(f"Notice: {notice}")
        agent_graph = build_graph(checkpointer, tools, model, today=today)

        with propagate_attributes(
            user_id="waffi",
            trace_name="cli-run",
            metadata={"prompt-version": settings.prompt_version},
        ):
            result = await agent_graph.ainvoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config
            )
            # HITL loop — handle zero or more interrupts per run.
            # The graph pauses at human_review_node whenever a write tool
            # is about to execute. We display the payload, collect the
            # decision, and resume with the same thread_id.
            while "__interrupt__" in result:
                for interrupt_obj in result["__interrupt__"]:
                    _display_interrupt(interrupt_obj.value)

                decision = _prompt_decision()
                print(f"\nResuming with: {decision}\n")

                result = await agent_graph.ainvoke(
                    Command(resume=decision),
                    config=config,
                )

    last = result["messages"][-1]
    print(_stringify_content(last.content))

    if debug:
        _display_debug_trace(result)

    # A Fixture-world run is about seeded stand-in data, not the owner's: keep it out of real memory.
    if not fixtures:
        log_run_to_memory(result, user_input)
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