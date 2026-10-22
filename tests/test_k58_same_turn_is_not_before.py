"""Kills M58: an ordering constraint met when both tools are called in the same model turn.

Parallel calls in one turn are written before any of their results exist, so a Draft proposed
alongside the Informer read can't have used it. No existing test has two calls in one turn.
"""

from agent.evals.records import ToolCallRecord
from agent.evals.scenarios import OrderingConstraint, Scenario
from agent.evals.trajectory import score_trajectory

READ, DRAFT = "informer_list_overdue_invoices", "ms365_create-draft-email"


def _call(name: str, step: int) -> ToolCallRecord:
    return ToolCallRecord(id=f"{name}-{step}", name=name, args={}, step=step, status="success", output="")


def test_a_draft_proposed_in_the_same_turn_as_the_read_is_not_after_it():
    scenario = Scenario(id="s", input="Draft reminders.", approval="approve", required_tools=[READ, DRAFT],
                        ordering=[OrderingConstraint(before=READ, after=DRAFT)])

    same_turn = score_trajectory(scenario, [_call(READ, 1), _call(DRAFT, 1)], completed=True)
    next_turn = score_trajectory(scenario, [_call(READ, 1), _call(DRAFT, 2)], completed=True)

    assert next_turn.ordering_met is True
    assert same_turn.ordering_met is False
    assert same_turn.passed is False
