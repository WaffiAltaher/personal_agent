"""
cli.py — Entry point with Langfuse tracing wired in.
"""

import sys
import uuid

from langchain_core.messages import HumanMessage
from langfuse import propagate_attributes
from langgraph.types import Command

from agent.graph import build_graph, get_checkpointer, log_run_to_memory
from agent.tracing import flush_traces, get_callback_handler, verify_connection
from agent.config import settings


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


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m agent.cli '<your question>'")
        sys.exit(1)

    # Verify Langfuse is reachable before we do any work.
    # This fails loudly rather than running the agent and silently losing traces.
    if not verify_connection():
        print("Warning: Langfuse connection failed. Traces will not be recorded.")
        # We continue anyway — observability failing shouldn't block the agent.

    user_input = sys.argv[1]
    
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
    }

    with get_checkpointer() as checkpointer:
        agent_graph = build_graph(checkpointer)

        with propagate_attributes(
            user_id="waffi",
            trace_name="cli-run",
            metadata={"prompt-version": settings.prompt_version},
        ):
            result = agent_graph.invoke(
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

                result = agent_graph.invoke(
                    Command(resume=decision),
                    config=config,
                )

    last = result["messages"][-1]
    if isinstance(last.content, str):
        print(last.content)
    else:
        text = " ".join(
            block["text"] for block in last.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        print(text)

    log_run_to_memory(result, user_input)
    flush_traces()


if __name__ == "__main__":
    main()