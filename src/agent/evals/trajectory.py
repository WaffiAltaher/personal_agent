# src/agent/evals/trajectory.py
"""Trajectory metrics (ADR-007): did the agent pick the right tools, in the right order,
stay away from forbidden ones, and recover from an injected failure?

All of it is computed from the run's tool calls, so it needs no judge model.
"""

from statistics import mean

from agent.evals.records import (
    FactsScore,
    OrderingResult,
    RunResult,
    Summary,
    ToolCallRecord,
    TrajectoryScore,
)
from agent.evals.scenarios import Scenario


def score_trajectory(scenario: Scenario, tool_calls: list[ToolCallRecord], *, completed: bool) -> TrajectoryScore:
    """Score one run. Precision and recall compare distinct tool names; an ordering constraint
    holds when `before` was first called in an earlier model turn than `after`.

    A run with an injected failure recovered when it still completed with a final answer (no
    crash, no step limit). A run passes when it completed, called every required tool, met
    every ordering constraint, called no forbidden tool and, if a failure was injected, recovered.
    Extra tools lower precision but do not fail the run.
    """
    called = {c.name for c in tool_calls}
    required = set(scenario.required_tools)
    hits = called & required
    precision = len(hits) / len(called) if called else 1.0
    recall = len(hits) / len(required) if required else 1.0

    first_step: dict[str, int] = {}
    for call in tool_calls:
        first_step.setdefault(call.name, call.step)
    ordering = [
        OrderingResult(
            before=c.before,
            after=c.after,
            met=c.before in first_step and c.after in first_step and first_step[c.before] < first_step[c.after],
        )
        for c in scenario.ordering
    ]
    ordering_met = all(o.met for o in ordering)

    violations = sorted(called & set(scenario.forbidden_tools))
    recovered = completed if scenario.inject_failure else None

    return TrajectoryScore(
        precision=precision,
        recall=recall,
        missing_tools=sorted(required - called),
        extra_tools=sorted(called - required),
        ordering=ordering,
        ordering_met=ordering_met,
        forbidden_violations=violations,
        recovered=recovered,
        passed=completed and recall == 1.0 and ordering_met and not violations and recovered is not False,
    )


def score_facts(scenario: Scenario, final_answer: str) -> FactsScore:
    answer = final_answer.lower()
    found = [f for f in scenario.expected_facts if f.lower() in answer]
    return FactsScore(found=found, missing=[f for f in scenario.expected_facts if f not in found])


def summarise(runs: list[RunResult]) -> Summary:
    """Aggregate the trajectory metrics over runs (means over runs; rates are shares of runs)."""
    if not runs:
        return Summary(runs=0, passed=0, pass_rate=0.0, mean_precision=0.0, mean_recall=0.0,
                       ordering_met_rate=0.0, forbidden_violations=0, recovery_rate=None, facts_rate=0.0)
    injected = [r.trajectory.recovered for r in runs if r.trajectory.recovered is not None]
    facts_expected = sum(len(r.answer_facts.found) + len(r.answer_facts.missing) for r in runs)
    passed = sum(r.passed for r in runs)
    outcome_runs = [r for r in runs if r.outcome.applicable]
    return Summary(
        runs=len(runs),
        passed=passed,
        pass_rate=passed / len(runs),
        mean_precision=mean(r.trajectory.precision for r in runs),
        mean_recall=mean(r.trajectory.recall for r in runs),
        ordering_met_rate=sum(r.trajectory.ordering_met for r in runs) / len(runs),
        forbidden_violations=sum(bool(r.trajectory.forbidden_violations) for r in runs),
        recovery_rate=sum(injected) / len(injected) if injected else None,
        facts_rate=sum(len(r.answer_facts.found) for r in runs) / facts_expected if facts_expected else 1.0,
        mean_outcome_rate=(
            sum(r.outcome.passed for r in outcome_runs) / len(outcome_runs) if outcome_runs else None
        ),
    )
