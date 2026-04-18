"""
cli.py — Entry point with Langfuse tracing wired in.
"""

import sys
from langchain_core.messages import HumanMessage
from langfuse import propagate_attributes

from agent.graph import agent_graph
from agent.tracing import flush_traces, get_callback_handler, verify_connection


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

    # One handler per run = one trace in Langfuse.
    langfuse_handler = get_callback_handler()

    with propagate_attributes(user_id="waffi", trace_name="cli-run"):
        result = agent_graph.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config={"callbacks": [langfuse_handler]},
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

    flush_traces()

if __name__ == "__main__":
    main()