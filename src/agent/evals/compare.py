"""The model-comparison report: two eval runs' results files side by side.

    uv run python -m agent.evals compare data/evals/<gemini-run>.json data/evals/<claude-run>.json

It is rendered from the two results files alone (EvalResults JSON, as the eval command writes
them), so it can be regenerated at any time. It compares the models on trajectory, answer
facts, generation (RAGAS), tokens, cost and latency: a summary over all runs, then a row per
scenario and model with the variation across repeats. It warns when the runs are not
comparable (different dataset or prompt versions) and when a model graded its own answers.
"""

from collections.abc import Callable
from pathlib import Path
from statistics import mean

from pydantic import ValidationError

from agent.evals.records import EvalResults, RunResult


class ResultsError(ValueError):
    """A file is missing or is not an eval results file."""


def load_results(path: Path | str) -> EvalResults:
    path = Path(path)
    try:
        return EvalResults.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise ResultsError(f"{path} is not a readable eval results file: {exc}") from exc


# --- formatting ----------------------------------------------------------------------------

def _num(value: float) -> str:
    return f"{value:.2f}"


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _usd(value: float) -> str:
    return f"${value:.4f}"


def _seconds(value: float) -> str:
    return f"{value:.1f}s"


def _tokens(value: float) -> str:
    return f"{value:.0f}"


def _opt(fmt: Callable[[float], str], value: float | None) -> str:
    return "n/a" if value is None else fmt(value)


def _spread(values: list[float | None], fmt: Callable[[float], str]) -> str:
    """The mean of the values that are there, with (min–max) when they differ; n/a if none is."""
    present = [v for v in values if v is not None]
    if not present:
        return "n/a"
    low, high = min(present), max(present)
    if fmt(low) == fmt(high):
        return fmt(mean(present))
    return f"{fmt(mean(present))} ({fmt(low)}–{fmt(high)})"


# --- the report ----------------------------------------------------------------------------

def _facts_share(run: RunResult) -> float | None:
    expected = len(run.answer_facts.found) + len(run.answer_facts.missing)
    return len(run.answer_facts.found) / expected if expected else None


def _judge(results: EvalResults) -> str:
    return "none" if results.judge_model is None else f"`{results.judge_model}`"


def _header(a: EvalResults, b: EvalResults, a_path: Path, b_path: Path) -> list[str]:
    lines = [
        f"# Model comparison: `{a.model}` vs `{b.model}`",
        "",
        f"- A: `{a.model}`: `{a_path}` (eval run `{a.eval_run_id}`, started {a.started_at})",
        f"- B: `{b.model}`: `{b_path}` (eval run `{b.eval_run_id}`, started {b.started_at})",
        f"- Dataset: `{a.dataset_path}` (version {a.dataset_version})"
        + ("" if a.dataset_version == b.dataset_version else f" vs version {b.dataset_version}"),
        f"- Prompt version: `{a.prompt_version}`" + ("" if a.prompt_version == b.prompt_version
                                                    else f" vs `{b.prompt_version}`"),
        f"- Repeats per scenario: {a.repeats} vs {b.repeats}",
        f"- Judge model: {_judge(a)} vs {_judge(b)}",
    ]
    warnings = []
    if a.dataset_version != b.dataset_version:
        warnings.append("Warning: the runs used different dataset versions, so the scenarios may differ.")
    if a.prompt_version != b.prompt_version:
        warnings.append("Warning: the runs used different prompt versions, so the models did not get the same prompt.")
    if a.scenario_filter != b.scenario_filter:
        warnings.append("Warning: the runs selected different scenarios (`--scenario`).")
    for r in (a, b):
        if r.judge_model is not None and r.judge_model == r.model:
            warnings.append(f"Warning: `{r.model}` graded its own answers (no separate judge model).")
    if a.judge_model != b.judge_model:
        warnings.append("Note: the runs had different judge models, so their RAGAS scores are graded differently.")
    if warnings:
        lines += [""] + [f"> {w}" for w in warnings]
    return lines


def _summary(a: EvalResults, b: EvalResults) -> list[str]:
    sa, sb = a.summary, b.summary

    def per_run(results: EvalResults, field: str) -> float | None:
        values = [getattr(r.efficiency, field) for r in results.runs if r.efficiency is not None]
        return None if not values or None in values else mean(values)

    def row(name: str, va: str, vb: str) -> str:
        return f"| {name} | {va} | {vb} |"

    return [
        "",
        "## Summary",
        "",
        "Over all runs (every scenario, every repeat).",
        "",
        f"| Metric | A: `{a.model}` | B: `{b.model}` |",
        "|---|---|---|",
        row("Passed", f"{sa.passed}/{sa.runs} ({_pct(sa.pass_rate)})", f"{sb.passed}/{sb.runs} ({_pct(sb.pass_rate)})"),
        row("Tool-selection precision (mean)", _num(sa.mean_precision), _num(sb.mean_precision)),
        row("Tool-selection recall (mean)", _num(sa.mean_recall), _num(sb.mean_recall)),
        row("Ordering constraints met", _pct(sa.ordering_met_rate), _pct(sb.ordering_met_rate)),
        row("Runs with forbidden-tool violations", str(sa.forbidden_violations), str(sb.forbidden_violations)),
        row("Recovery after injected failure", _opt(_pct, sa.recovery_rate), _opt(_pct, sb.recovery_rate)),
        row("Expected answer facts found", _pct(sa.facts_rate), _pct(sb.facts_rate)),
        row("Faithfulness (mean)", _opt(_num, sa.mean_faithfulness), _opt(_num, sb.mean_faithfulness)),
        row("Answer relevancy (mean)", _opt(_num, sa.mean_answer_relevancy), _opt(_num, sb.mean_answer_relevancy)),
        row("Context precision (mean)", _opt(_num, sa.mean_context_precision), _opt(_num, sb.mean_context_precision)),
        row("Context recall (mean)", _opt(_num, sa.mean_context_recall), _opt(_num, sb.mean_context_recall)),
        row("Total tokens", str(sa.total_tokens), str(sb.total_tokens)),
        row("Tokens per run (mean)", _opt(_tokens, per_run(a, "total_tokens")), _opt(_tokens, per_run(b, "total_tokens"))),
        row("Total cost", _opt(_usd, sa.total_cost_usd), _opt(_usd, sb.total_cost_usd)),
        row("Cost per run (mean)", _opt(_usd, per_run(a, "cost_usd")), _opt(_usd, per_run(b, "cost_usd"))),
        row("Mean latency", _opt(_seconds, sa.mean_latency_s), _opt(_seconds, sb.mean_latency_s)),
    ]


def _scenario_row(scenario_id: str, model: str, runs: list[RunResult]) -> str:
    if not runs:
        return f"| {scenario_id} | `{model}` | not run | | | | | | | | |"
    passed = sum(r.trajectory.passed for r in runs)
    cells = [
        f"{passed}/{len(runs)}",
        _spread([r.trajectory.recall for r in runs], _num),
        _spread([r.trajectory.precision for r in runs], _num),
        _spread([_facts_share(r) for r in runs], _pct),
        _spread([r.generation.faithfulness if r.generation else None for r in runs], _num),
        _spread([r.generation.answer_relevancy if r.generation else None for r in runs], _num),
        _spread([r.efficiency.total_tokens if r.efficiency else None for r in runs], _tokens),
        # A run with an unpriced model has no cost: the mean is then over the priced runs only.
        _spread([r.efficiency.cost_usd if r.efficiency else None for r in runs], _usd),
        _spread([r.efficiency.latency_s if r.efficiency else None for r in runs], _seconds),
    ]
    return f"| {scenario_id} | `{model}` | " + " | ".join(cells) + " |"


def _scenarios(a: EvalResults, b: EvalResults) -> list[str]:
    ids = list(dict.fromkeys([r.scenario_id for r in a.runs] + [r.scenario_id for r in b.runs]))
    lines = [
        "",
        "## Per scenario",
        "",
        "Each cell is the mean over the scenario's repeats, with the spread (min–max) when the",
        "repeats differ. Passed counts the passing repeats; Facts is the share of expected answer",
        "facts found; n/a means not scored or not recorded.",
        "",
        "| Scenario | Model | Passed | Recall | Precision | Facts | Faithfulness | Answer relevancy "
        "| Tokens | Cost | Latency |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for scenario_id in ids:
        for results in (a, b):
            lines.append(_scenario_row(scenario_id, results.model,
                                       [r for r in results.runs if r.scenario_id == scenario_id]))
    return lines


def render_comparison(a: EvalResults, b: EvalResults, *, a_path: Path | str = "", b_path: Path | str = "") -> str:
    lines = _header(a, b, Path(a_path), Path(b_path)) + _summary(a, b) + _scenarios(a, b)
    return "\n".join(lines) + "\n"


def write_comparison(a_path: Path | str, b_path: Path | str, out_dir: Path | str) -> Path:
    """Render the comparison of two results files into `compare-<run A>-vs-<run B>.md` in out_dir."""
    a, b = load_results(a_path), load_results(b_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"compare-{a.eval_run_id}-vs-{b.eval_run_id}.md"
    path.write_text(render_comparison(a, b, a_path=a_path, b_path=b_path))
    return path
