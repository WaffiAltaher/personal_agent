"""
tests/test_graph.py

Tests for the LangGraph ReAct graph.

Two levels of testing here:

1. Unit test for should_continue() — pure routing logic, no I/O at all.
   We hand-craft AIMessage objects and assert on the routing decision.

2. Integration test for the full graph — the graph structure, ToolNode,
   add_messages reducer, and routing all run for real. Only the LLM is
   replaced: a scripted fake model is injected via build_graph(model=...).

Why mock the LLM but not the tool?
   The LLM is the only non-deterministic, paid, slow dependency. The tool
   is fast, free, and deterministic — letting it run for real gives us more
   confidence that the full stack is wired correctly.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END
from agent.graph import AgentState, build_graph, should_continue
from agent.tools.classification import read_tool


# ---------------------------------------------------------------------------
# 1. Routing logic — pure unit test
# ---------------------------------------------------------------------------

def test_should_continue_routes_to_tools_when_tool_call_present():
    """
    When the last AIMessage contains tool_calls, the router must return "tools".
    This is the branch that kicks off the tool execution node.
    """
    # Construct an AIMessage that looks like a tool-calling response.
    # tool_calls is a list of dicts with id, name, and args.
    message_with_tool_call = AIMessage(
        content="",
        tool_calls=[{
            "id": "call_123",
            "name": "read_file",
            "args": {"path": "/tmp/notes.txt"},
        }]
    )
    state: AgentState = {"messages": [message_with_tool_call]}

    assert should_continue(state) == "human_review"


def test_should_continue_routes_to_end_when_no_tool_call():
    """
    When the last AIMessage has plain text and no tool_calls,
    the router must return END. This terminates the graph.
    """
    final_answer = AIMessage(content="The secret word is banana.")
    state: AgentState = {"messages": [final_answer]}

    assert should_continue(state) == END


# ---------------------------------------------------------------------------
# 2. Full graph integration test — LLM mocked, everything else real
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graph_executes_react_loop(tmp_path, scripted_model):
    """
    End-to-end test of the ReAct loop with a mocked LLM.

    Script:
      Turn 1 — LLM receives the user question, returns a tool call for read_file.
      Turn 2 — LLM receives the tool result, returns the final answer.

    Everything except the LLM runs for real:
      - The graph structure and edges
      - The add_messages reducer (state accumulation)
      - The ToolNode (actual tool invocation via read_file)
      - The should_continue routing function

    This test verifies that the wiring is correct end-to-end.
    """
    # Set up a real file for the tool to read
    test_file = tmp_path / "notes.txt"
    test_file.write_text("the secret word is mango")

    # --- Script the two LLM responses ---

    # Response 1: the LLM decides to call read_file
    first_response = AIMessage(
        content="",
        tool_calls=[{
            "id": "call_abc",
            "name": "read_file",
            "args": {"path": str(test_file)},
        }]
    )

    # Response 2: the LLM has seen the tool result and produces the final answer
    second_response = AIMessage(content="The secret word is mango.")

    # Inject a scripted fake model so build_graph() never builds a real one.
    graph = build_graph(model=scripted_model([first_response, second_response]))
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="What is the secret word?")]}
    )

    # The final state should contain the full message history:
    # HumanMessage → AIMessage (tool call) → ToolMessage (tool result) → AIMessage (answer)
    messages = result["messages"]
    assert len(messages) == 4

    # The last message must be the final answer from the LLM
    last = messages[-1]
    assert isinstance(last, AIMessage)
    assert "mango" in last.content

    # The second-to-last must be the ToolMessage produced by the real tool
    tool_msg = messages[-2]
    assert isinstance(tool_msg, ToolMessage)
    assert "the secret word is mango" in tool_msg.content


@pytest.mark.asyncio
async def test_graph_records_structured_tool_errors(scripted_model):
    """
    When the tool node fails with an exception, the graph should both:
      - return ToolMessages so the LLM message history remains valid
      - preserve structured error details for developer/debug output
    """

    @read_tool
    @tool("explode")
    async def explode() -> str:
        """Raise a deterministic exception for testing fallback behavior."""
        raise RuntimeError("boom")

    first_response = AIMessage(
        content="",
        tool_calls=[{
            "id": "call_explode",
            "name": "explode",
            "args": {},
        }]
    )
    second_response = AIMessage(content="The tool failed.")

    graph = build_graph(tools=[explode], model=scripted_model([first_response, second_response]))
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Trigger the failing tool.")]}
    )

    assert result["errors"] == [{
        "node": "tools",
        "tool": "explode",
        "tool_call_id": "call_explode",
        "args": {},
        "exception_type": "RuntimeError",
        "message": "boom",
    }]

    tool_msg = result["messages"][-2]
    assert isinstance(tool_msg, ToolMessage)
    assert "RuntimeError: boom" in tool_msg.content
