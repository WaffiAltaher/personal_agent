"""Kills M65: the eval harness's step limit raised from 40 to 400 super-steps.

No test runs an eval scenario that never ends, so the limit is never reached. A model that
asks for a tool on every turn should be stopped after the configured number of model calls,
and the run recorded as `step_limit`, not left to run (and bill) for a hundred rounds.
"""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent.config import settings
from agent.evals.harness import run_scenario
from agent.evals.scenarios import Scenario
from agent.tools.classification import read_tool


@tool
def ping() -> str:
    """Return pong."""
    return "pong"


@pytest.mark.asyncio
async def test_a_run_that_never_ends_is_stopped_at_the_step_limit(scripted_model, monkeypatch):
    monkeypatch.setattr(settings, "max_iterations", 7)
    calls = []

    def forever(messages):
        calls.append(1)
        return AIMessage(content="", tool_calls=[{"id": f"p{len(calls)}", "name": "ping", "args": {}}])

    async def only_ping():
        return [read_tool(ping)], []

    scenario = Scenario(id="loop", input="go", approval="approve", required_tools=["ping"])
    run = await run_scenario(scenario, model=scripted_model([forever] * 500), model_name="scripted",
                             load_tools=only_ping)

    assert run.status == "step_limit"
    assert len(calls) == 7
    assert run.trajectory.passed is False
