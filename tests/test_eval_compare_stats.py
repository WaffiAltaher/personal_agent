"""Comparison statistics and judge labels (ticket 23)."""

from math import sqrt
from statistics import mean, stdev

import pytest

from agent.evals.compare import render_comparison
from agent.evals.generation import generation_means
from agent.evals.records import (
    EvalResults,
    FactsScore,
    GenerationScores,
    RunResult,
    TrajectoryScore,
)
from agent.evals.trajectory import summarise


def _trajectory(*, passed: bool) -> TrajectoryScore:
    return TrajectoryScore(
        precision=1.0,
        recall=1.0,
        missing_tools=[],
        extra_tools=[],
        ordering=[],
        ordering_met=True,
        forbidden_violations=[],
        recovered=None,
        passed=passed,
    )


def _run(
    scenario_id: str,
    repeat: int,
    model: str,
    *,
    passed: bool,
    faithfulness: float | None = None,
) -> RunResult:
    generation = None
    if faithfulness is not None:
        generation = GenerationScores(faithfulness=faithfulness, answer_relevancy=0.5)
    return RunResult(
        scenario_id=scenario_id,
        workflow="test",
        repeat=repeat,
        model=model,
        input="q",
        status="completed",
        final_answer="a",
        tool_calls=[],
        interrupts=[],
        notices=[],
        drafts=[],
        trajectory=_trajectory(passed=passed),
        answer_facts=FactsScore(found=[], missing=[]),
        generation=generation,
    )


def _results(
    model: str,
    runs: list[RunResult],
    *,
    judge_model: str | None = None,
    repeats: int = 1,
) -> EvalResults:
    summary = summarise(runs).model_copy(update=generation_means(runs))
    return EvalResults(
        eval_run_id=f"run-{model.split(':')[-1]}",
        started_at="2026-01-01T00:00:00Z",
        model=model,
        judge_model=judge_model,
        prompt_version="v1",
        dataset_path="scenarios.json",
        dataset_version="v1",
        scenario_filter=None,
        repeats=repeats,
        runs=runs,
        summary=summary,
    )


def _paired_runs(
    scenario_passes: dict[str, tuple[list[bool], list[bool]]],
    model_a: str,
    model_b: str,
    repeats: int,
) -> tuple[EvalResults, EvalResults]:
    runs_a: list[RunResult] = []
    runs_b: list[RunResult] = []
    for scenario_id, (passes_a, passes_b) in scenario_passes.items():
        for repeat, passed in enumerate(passes_a):
            runs_a.append(_run(scenario_id, repeat, model_a, passed=passed))
        for repeat, passed in enumerate(passes_b):
            runs_b.append(_run(scenario_id, repeat, model_b, passed=passed))
    return (
        _results(model_a, runs_a, repeats=repeats),
        _results(model_b, runs_b, repeats=repeats),
    )


def test_small_pass_rate_gap_says_models_cannot_be_told_apart():
    # Eighteen scenarios, three repeats: identical pass/fail on A and B → paired diffs are all zero.
    scenarios = {
        f"s{i}": ([True, False, True], [True, False, True]) for i in range(18)
    }
    a, b = _paired_runs(scenarios, "google_genai:gemini-3.8-flash", "anthropic:claude-sonnet-5-5", 3)
    report = render_comparison(a, b)
    assert "can't tell these apart with this many runs" in report.lower()


def test_large_pass_rate_gap_does_not_say_cannot_be_told_apart():
    scenarios = {
        f"s{i}": ([False, False, False], [True, True, True]) for i in range(18)
    }
    a, b = _paired_runs(scenarios, "google_genai:gemini-3.8-flash", "anthropic:claude-sonnet-5-5", 3)
    report = render_comparison(a, b)
    assert "can't tell these apart with this many runs" not in report.lower()


def test_paired_interval_clusters_by_scenario_not_pooled_runs():
    # Two scenarios with very different repeat counts; paired mean is 30%, not the pooled 17%.
    scenarios = {
        "heavy": ([True] * 5 + [False] * 5, [True] * 6 + [False] * 4),
        "light": ([True, False], [True, True]),
    }
    a, b = _paired_runs(scenarios, "google_genai:gemini-a", "google_genai:gemini-b", repeats=10)
    diffs = [0.6 - 0.5, 1.0 - 0.5]
    expected_mean = mean(diffs)
    se = stdev(diffs) / sqrt(len(diffs))
    low = expected_mean - 1.96 * se
    high = expected_mean + 1.96 * se
    report = render_comparison(a, b)
    assert f"{expected_mean:.0%}" in report
    assert f"{low:.0%}" in report
    assert f"{high:.0%}" in report
    pooled = (6 + 2) / 12 - (5 + 1) / 12
    assert f"{pooled:.0%}" not in report.replace(f"{expected_mean:.0%}", "")


def test_pass_all_repeats_counts_only_scenarios_that_passed_every_repeat():
    scenarios = {
        "always": ([True, True, True], [True, True, True]),
        "sometimes": ([True, True, False], [True, False, True]),
    }
    a, b = _paired_runs(scenarios, "google_genai:gemini-a", "google_genai:gemini-b", repeats=3)
    report = render_comparison(a, b)
    assert "pass^3" in report.lower() or "pass^k" in report.lower()
    # Model A: only "always" passed all three repeats → 1/2 scenarios.
    assert "`google_genai:gemini-a`" in report
    assert "1/2" in report or "50%" in report


def test_same_provider_judge_warns_different_provider_does_not():
    anthropic = _results(
        "anthropic:claude-sonnet-5-5",
        [_run("s0", 0, "anthropic:claude-sonnet-5-5", passed=True)],
        judge_model="anthropic:claude-opus-5-5",
    )
    google = _results(
        "google_genai:gemini-3.8-flash",
        [_run("s0", 0, "google_genai:gemini-3.8-flash", passed=True)],
        judge_model="anthropic:claude-opus-5-5",
    )
    assert "same provider" in render_comparison(anthropic, google).lower()

    both_google = _results(
        "google_genai:gemini-3.8-flash",
        [_run("s0", 0, "google_genai:gemini-3.8-flash", passed=True)],
        judge_model="anthropic:claude-opus-5-5",
    )
    other_judge = _results(
        "google_genai:gemini-3.8-flash",
        [_run("s0", 0, "google_genai:gemini-3.8-flash", passed=True)],
        judge_model="openai:gpt-5",
    )
    assert "same provider" not in render_comparison(both_google, other_judge).lower()


def test_answer_quality_means_show_how_many_runs_were_scored():
    runs = [
        _run("s0", 0, "google_genai:gemini-a", passed=True, faithfulness=1.0),
        _run("s0", 1, "google_genai:gemini-a", passed=True, faithfulness=0.0),
        _run("s1", 0, "google_genai:gemini-a", passed=True),
        _run("s1", 1, "google_genai:gemini-a", passed=True),
    ]
    a = _results("google_genai:gemini-a", runs, judge_model="anthropic:claude-opus-5-5", repeats=2)
    b = _results(
        "anthropic:claude-sonnet-5-5",
        [_run("s0", 0, "anthropic:claude-sonnet-5-5", passed=True)],
        judge_model="anthropic:claude-opus-5-5",
    )
    report = render_comparison(a, b)
    assert "unvalidated llm judge" in report.lower()
    assert "2" in report and "scored" in report.lower()
