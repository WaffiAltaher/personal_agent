"""
tests/test_eval_compare.py

The model-comparison report, end to end with scripted models: two eval runs over the test
dataset with two repeats each are written as results files, as `python -m agent.evals` writes
them, and `python -m agent.evals compare a.json b.json` renders the report from those files.

- Model A ("Gemini") plays the well-behaved scripts every time: the reply scenario passes,
  the rejected-reminders scenario fails; a scripted judge grades its answers.
- Model B ("Claude") behaves on the first reply run, then gives up without a tool call; it
  gives up on the reminders scenario both times. It ran without a judge.
"""

import itertools
import json

import pytest
import pytest_asyncio

import agent.graph as graph_module
from agent.evals.__main__ import main
from agent.evals.generation import RagasScorer
from agent.evals.harness import run_eval, write_results
from agent.evals.records import EvalResults
from agent.evals.scenarios import load_dataset
from test_eval_harness import DATASET, SCRIPTS, ScriptedEmbeddings, _answer, _judge_reply

GIVE_UP = [_answer("I could not find that.")]


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    monkeypatch.setattr(graph_module, "TOOL_RETRY_POLICY",
                        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False))


_RUNS: dict[str, EvalResults] = {}  # the two eval runs, made once for the module (they take a while)


@pytest_asyncio.fixture
async def results_files(scripted_model, tmp_path):
    if not _RUNS:
        _RUNS["a"] = await run_eval(
            load_dataset(DATASET), model_name="google_genai:gemini-3.8-flash", repeats=2,
            model_factory=lambda scenario: scripted_model(SCRIPTS[scenario.id]),
            scorer=RagasScorer(judge=scripted_model(itertools.repeat(_judge_reply)), embeddings=ScriptedEmbeddings()),
            judge_model="anthropic:claude-sonnet-5-5",
        )
        b_scripts = {"reply-flaky-mailbox": iter([SCRIPTS["reply-flaky-mailbox"], GIVE_UP]),
                     "reply-sanne-rejected": iter([GIVE_UP, GIVE_UP])}
        _RUNS["b"] = await run_eval(
            load_dataset(DATASET), model_name="anthropic:claude-sonnet-5-5", repeats=2,
            model_factory=lambda scenario: scripted_model(next(b_scripts[scenario.id])),
        )
    a, b = _RUNS["a"], _RUNS["b"]
    a_path, _ = write_results(a, tmp_path / "a")
    b_path, _ = write_results(b, tmp_path / "b")
    return a_path, b_path


@pytest_asyncio.fixture
async def report(results_files, tmp_path, capsys):
    a_path, b_path = results_files
    await main(["compare", str(a_path), str(b_path), "--out", str(tmp_path / "out")])
    [path] = (tmp_path / "out").glob("*.md")
    assert str(path) in capsys.readouterr().out
    return path.read_text()


def _row(report: str, start: str) -> str:
    [row] = [line for line in report.splitlines() if line.startswith(start)]
    return row


@pytest.mark.asyncio
async def test_report_names_both_models_runs_and_judges(report, results_files):
    a_path, b_path = results_files
    a_id, b_id = a_path.stem, b_path.stem
    assert report.startswith("# Model comparison: `google_genai:gemini-3.8-flash` vs `anthropic:claude-sonnet-5-5`")
    assert f"eval run `{a_id}`" in report and f"eval run `{b_id}`" in report
    assert "- Repeats per scenario: 2 vs 2" in report
    assert "- Judge model: `anthropic:claude-sonnet-5-5` vs none" in report


@pytest.mark.asyncio
async def test_summary_compares_trajectory_quality_cost_tokens_and_latency(report):
    assert _row(report, "| Passed |") == "| Passed | 2/4 (50%) | 1/4 (25%) |"
    assert _row(report, "| Tool-selection recall (mean) |") == "| Tool-selection recall (mean) | 0.75 | 0.25 |"
    assert _row(report, "| Tool-selection precision (mean) |") == "| Tool-selection precision (mean) | 0.75 | 1.00 |"
    assert _row(report, "| Recovery after injected failure |") == "| Recovery after injected failure | 100% | 100% |"
    assert _row(report, "| Faithfulness (mean) |") == (
        "| Faithfulness (mean) | 0.50 (2/4 runs scored, unvalidated LLM judge) | n/a |"
    )
    assert _row(report, "| Answer relevancy (mean) |") == (
        "| Answer relevancy (mean) | 0.60 (4/4 runs scored, unvalidated LLM judge) | n/a |"
    )
    # A: 3 + 3 model calls per repeat; B: 3 + 1 + 1 + 1. 1100 tokens, $0.003 per call.
    assert _row(report, "| Total tokens |") == "| Total tokens | 13200 | 6600 |"
    assert _row(report, "| Tokens per run (mean) |") == "| Tokens per run (mean) | 3300 | 1650 |"
    assert _row(report, "| Total cost |") == "| Total cost | $0.0360 | $0.0180 |"
    assert _row(report, "| Cost per run (mean) |") == "| Cost per run (mean) | $0.0090 | $0.0045 |"
    assert _row(report, "| Mean latency |").startswith("| Mean latency | ")


@pytest.mark.asyncio
async def test_per_scenario_rows_show_the_variation_across_repeats(report):
    # Scenario | Model | Passed | Recall | Precision | Facts | Faithfulness | Answer relevancy | Tokens | Cost | Latency
    a_reply = _row(report, "| reply-flaky-mailbox | `google_genai:gemini-3.8-flash` |")
    assert a_reply.startswith("| reply-flaky-mailbox | `google_genai:gemini-3.8-flash` | 2/2 | 1.00 | 1.00 "
                              "| 100% | 0.50 | 0.60 | 3300 | $0.0090 |")
    b_reply = _row(report, "| reply-flaky-mailbox | `anthropic:claude-sonnet-5-5` |")
    # One repeat passed, the other gave up: the spread is shown as (min–max).
    assert b_reply.startswith("| reply-flaky-mailbox | `anthropic:claude-sonnet-5-5` | 1/2 | 0.50 (0.00–1.00) "
                              "| 1.00 | 50% (0%–100%) | n/a | n/a | 2200 (1100–3300) "
                              "| $0.0060 ($0.0030–$0.0090) |")
    b_rejected = _row(report, "| reply-sanne-rejected | `anthropic:claude-sonnet-5-5` |")
    assert b_rejected.startswith("| reply-sanne-rejected | `anthropic:claude-sonnet-5-5` | 0/2 | 0.00 | 1.00 "
                                 "| 0% | n/a | n/a | 1100 | $0.0030 |")


@pytest.mark.asyncio
async def test_report_warns_when_a_model_grades_its_own_answers(results_files, tmp_path, capsys):
    a_path, b_path = results_files
    data = json.loads(b_path.read_text())
    data["judge_model"] = data["model"]
    b_path.write_text(json.dumps(data))

    await main(["compare", str(a_path), str(b_path), "--out", str(tmp_path / "out")])

    [path] = (tmp_path / "out").glob("*.md")
    assert "`anthropic:claude-sonnet-5-5` graded its own answers" in path.read_text()


@pytest.mark.asyncio
async def test_report_warns_when_the_runs_are_not_comparable(results_files, tmp_path):
    a_path, b_path = results_files
    data = json.loads(b_path.read_text())
    data["dataset_version"] = "other"
    data["prompt_version"] = "v0"
    b_path.write_text(json.dumps(data))

    await main(["compare", str(a_path), str(b_path), "--out", str(tmp_path / "out")])

    report = next((tmp_path / "out").glob("*.md")).read_text()
    assert "Warning: the runs used different dataset versions" in report
    assert "Warning: the runs used different prompt versions" in report


@pytest.mark.asyncio
async def test_compare_rejects_a_file_that_is_not_results(tmp_path, results_files):
    a_path, _ = results_files
    bogus = tmp_path / "bogus.json"
    bogus.write_text("{}")

    with pytest.raises(ValueError, match="bogus.json"):
        await main(["compare", str(a_path), str(bogus), "--out", str(tmp_path / "out")])
