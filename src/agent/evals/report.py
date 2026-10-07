# src/agent/evals/report.py
"""The markdown report for one eval run: the trajectory summary and a row per scenario run, the
generation (RAGAS) scores, tokens/cost/latency, and why each failing run failed. It is rendered from EvalResults alone, so it can be regenerated from a
results JSON file."""

from agent.evals.records import EvalResults, RunResult


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _judge_line(results: EvalResults) -> str:
    if results.judge_model is None:
        return "- Judge model: none"
    own = " (the model under test: it grades its own answers)" if results.judge_model == results.model else ""
    return f"- Judge model: `{results.judge_model}`{own}"


def _score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _generation_lines(results: EvalResults) -> list[str]:
    lines = ["", "## Generation (RAGAS)", ""]
    if results.judge_model is None:
        return lines + ["Not scored: the eval ran without a judge model."]
    s = results.summary
    lines += [
        "Contexts are the run's successful tool outputs; the reference is the scenario's expected",
        "facts. n/a means not scored (the reason is in the results JSON, `generation.notes`).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Faithfulness (mean) | {_score(s.mean_faithfulness)} |",
        f"| Answer relevancy (mean) | {_score(s.mean_answer_relevancy)} |",
        f"| Context precision (mean) | {_score(s.mean_context_precision)} |",
        f"| Context recall (mean) | {_score(s.mean_context_recall)} |",
        "",
        "| Scenario | Faithfulness | Answer relevancy | Context precision | Context recall | Contexts |",
        "|---|---|---|---|---|---|",
    ]
    for run in results.runs:
        g = run.generation
        if g is None:
            lines.append(f"| {run.scenario_id} | n/a | n/a | n/a | n/a | n/a |")
        else:
            lines.append(f"| {run.scenario_id} | {_score(g.faithfulness)} | {_score(g.answer_relevancy)} "
                         f"| {_score(g.context_precision)} | {_score(g.context_recall)} | {g.contexts} |")
    return lines


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def _efficiency_lines(results: EvalResults) -> list[str]:
    s = results.summary
    lines = [
        "",
        "## Efficiency",
        "",
        "Cost is priced from the dated table in `agent/evals/pricing.py`; n/a means a model or",
        "usage the table has no price for.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total tokens | {s.total_tokens} |",
        f"| Total cost | {_usd(s.total_cost_usd)} |",
        f"| Mean latency | {_seconds(s.mean_latency_s)} |",
        "",
        "| Scenario | Input tokens | Output tokens | Cost | Latency |",
        "|---|---|---|---|---|",
    ]
    for run in results.runs:
        e = run.efficiency
        if e is None:
            lines.append(f"| {run.scenario_id} | n/a | n/a | n/a | n/a |")
        else:
            lines.append(f"| {run.scenario_id} | {e.input_tokens} | {e.output_tokens} | {_usd(e.cost_usd)} "
                         f"| {_seconds(e.latency_s)} |")
    return lines


def failure_reasons(run: RunResult) -> list[str]:
    """Why a run did not pass, in words."""
    reasons = []
    if run.status != "completed":
        reasons.append(f"run ended with status {run.status}" + (f" ({run.error})" if run.error else ""))
    elif not run.final_answer:
        reasons.append("no final answer")
    score = run.trajectory
    if score.missing_tools:
        reasons.append(f"missing required tools: {', '.join(score.missing_tools)}")
    for o in score.ordering:
        if not o.met:
            reasons.append(f"ordering not met: {o.before} before {o.after}")
    if score.forbidden_violations:
        reasons.append(f"forbidden tools called: {', '.join(score.forbidden_violations)}")
    if score.recovered is False:
        reasons.append("did not recover from the injected failure")
    return reasons


def render_report(results: EvalResults) -> str:
    s = results.summary
    lines = [
        f"# Eval run {results.eval_run_id}",
        "",
        f"- Model: `{results.model}`",
        _judge_line(results),
        f"- Prompt version: `{results.prompt_version}`",
        f"- Dataset: `{results.dataset_path}` (version {results.dataset_version})"
        + (f", scenarios matching `{results.scenario_filter}`" if results.scenario_filter else ""),
        f"- Started: {results.started_at}",
        "",
        "## Trajectory summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Passed | {s.passed}/{s.runs} ({_pct(s.pass_rate)}) |",
        f"| Tool-selection precision (mean) | {s.mean_precision:.2f} |",
        f"| Tool-selection recall (mean) | {s.mean_recall:.2f} |",
        f"| Ordering constraints met | {_pct(s.ordering_met_rate)} |",
        f"| Runs with forbidden-tool violations | {s.forbidden_violations} |",
        f"| Recovery after injected failure | {_pct(s.recovery_rate)} |",
        f"| Expected answer facts found | {_pct(s.facts_rate)} |",
        "",
        "## Scenarios",
        "",
        "| Scenario | Result | Precision | Recall | Ordering | Forbidden | Recovered | Facts | Tools called |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run in results.runs:
        t = run.trajectory
        facts = len(run.answer_facts.found), len(run.answer_facts.found) + len(run.answer_facts.missing)
        tools = " → ".join(f"{c.name}" + ("" if c.status == "success" else f" ({c.status})") for c in run.tool_calls)
        lines.append(
            f"| {run.scenario_id} | {'PASS' if t.passed else 'FAIL'} | {t.precision:.2f} | {t.recall:.2f} "
            f"| {'met' if t.ordering_met else 'not met'} | {', '.join(t.forbidden_violations) or 'none'} "
            f"| {'n/a' if t.recovered is None else ('yes' if t.recovered else 'no')} "
            f"| {facts[0]}/{facts[1]} | {tools or '—'} |"
        )

    lines += _generation_lines(results)
    lines += _efficiency_lines(results)

    failing = [run for run in results.runs if not run.trajectory.passed]
    if failing:
        lines += ["", "## Failures", ""]
        for run in failing:
            lines.append(f"- **{run.scenario_id}**: {'; '.join(failure_reasons(run))}")
    return "\n".join(lines) + "\n"
