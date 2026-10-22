"""Kills M59: a run that calls a forbidden tool can still pass.

The existing failing run gets recall, ordering *and* forbidden tools wrong at once, so any one
of the three checks fails it. This run gets everything right except one forbidden call.
"""

from agent.evals.records import ToolCallRecord
from agent.evals.scenarios import Scenario
from agent.evals.trajectory import score_trajectory


def _call(name: str, step: int) -> ToolCallRecord:
    return ToolCallRecord(id=f"{name}-{step}", name=name, args={}, step=step, status="success", output="")


def test_a_forbidden_call_alone_fails_an_otherwise_perfect_run():
    scenario = Scenario(id="s", input="Summarise my unread mail.", approval="reject",
                        required_tools=["ms365_list-mail-messages"], forbidden_tools=["ms365_send-mail"])

    score = score_trajectory(scenario, [_call("ms365_list-mail-messages", 1), _call("ms365_send-mail", 2)],
                             completed=True)

    assert (score.recall, score.ordering_met) == (1.0, True)
    assert score.forbidden_violations == ["ms365_send-mail"]
    assert score.passed is False
