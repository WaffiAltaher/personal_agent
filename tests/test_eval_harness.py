"""
tests/test_eval_harness.py

The eval harness (ADR-007, trajectory level) with a scripted fake model on two scenarios over
the Fixture world: the graph runs with the Informer and MS365 tools loaded over real MCP, as
`--fixtures` loads them. One scenario's script plays a well-behaved agent and passes; the
other's plays an agent that gets the trajectory wrong. Assertions are on the scenario loader,
the per-run result records, the scores, and the results JSON and report the harness writes.
"""

import itertools
import json
from pathlib import Path

import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.__main__ import main
from agent.evals.generation import RagasScorer
from agent.evals.harness import run_eval, write_results
from agent.evals.records import EvalResults
from agent.evals.scenarios import ScenarioError, load_dataset

DATASET = Path(__file__).parent / "fixtures" / "evals" / "scenarios.json"


# --- scenario format -----------------------------------------------------------------------

def test_dataset_loads_with_its_version_and_scenarios():
    dataset = load_dataset(DATASET)

    assert dataset.format_version == 1
    assert dataset.dataset_version == "test-2026-10-07"
    reply, rejected = dataset.scenarios
    assert reply.id == "reply-flaky-mailbox"
    assert reply.approval == "approve"
    assert reply.inject_failure.server == "ms365"
    assert reply.inject_failure.mode == "transient"
    assert reply.inject_failure.times == 1
    assert rejected.approval == "reject"
    assert rejected.inject_failure is None
    assert rejected.ordering[0].before == "informer_list_overdue_invoices"
    assert rejected.forbidden_tools == ["create_draft_email", "ms365_send-mail"]
    assert rejected.expected_facts == ["Noordzee Advies"]


@pytest.mark.parametrize("change, complaint", [
    ({"format_version": 2}, "unsupported format_version 2"),
    ({"scenarios": [{"id": "x", "input": "hi", "approval": "maybe"}]}, "approval"),
    ({"scenarios": [{"id": "x", "input": "hi", "approval": "approve",
                     "inject_failure": {"server": "informer", "mode": "offline"}}]}, "unknown informer failure mode"),
    ({"scenarios": [{"id": "x", "input": "hi", "approval": "approve", "expected_answer": "typo"}]}, "expected_answer"),
])
def test_invalid_dataset_is_rejected_with_the_reason(tmp_path, change, complaint):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps({"format_version": 1, "dataset_version": "v", "scenarios": [], **change}))

    with pytest.raises(ScenarioError, match=complaint):
        load_dataset(path)


# --- running and scoring -------------------------------------------------------------------

QUESTION_ID = "AAMkAGZpeHR1cmUAMESSAGE02"  # Jan de Bakker's question about invoice 2026-031


# Every scripted reply reports the usage a Claude Sonnet 5.5 call would: 1000 tokens in, 100 out.
USAGE = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
METADATA = {"model_name": "claude-sonnet-5-5"}


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}],
                     usage_metadata=USAGE, response_metadata=METADATA)


def _answer(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata=USAGE, response_metadata=METADATA)


REMINDER = {"body": {
    "subject": "Payment reminder",
    "body": {"contentType": "text", "content": "Dear client, please pay."},
    "toRecipients": [{"emailAddress": {"address": "facturen@goudenbol.example"}}],
}}

SCRIPTS = {
    # Well behaved: finds the mail (the mailbox fails once and the read is retried), then
    # proposes the reply Draft, which the harness approves.
    "reply-flaky-mailbox": [
        _call("ms365_list-mail-messages", {"search": '"invoice 2026-031"', "select": "id,subject,from"}, "search"),
        _call("ms365_create-reply-draft",
              {"messageId": QUESTION_ID, "body": {"Comment": "Happy to go through the hours on Tuesday."}}, "reply"),
        _answer("I saved a reply to Jan in your Drafts: you'll go through the hours on Tuesday."),
    ],
    # Gets the trajectory wrong: tries Gmail (forbidden), then drafts a reminder without
    # reading Informer first. The harness rejects both.
    "overdue-reminders-rejected": [
        _call("create_draft_email", {"to": "facturen@goudenbol.example", "subject": "Reminder", "body": "Pay"}, "gmail"),
        _call("ms365_create-draft-email", REMINDER, "draft"),
        _answer("Understood, I did not save any reminders."),
    ],
}


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    """Keep the retry semantics but skip the real sleeps."""
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


@pytest.fixture
def evaluate(scripted_model):
    async def evaluate(scenario_filter: str | None = None):
        return await run_eval(
            load_dataset(DATASET),
            model_name="scripted",
            model_factory=lambda scenario: scripted_model(SCRIPTS[scenario.id]),
            scenario_filter=scenario_filter,
        )
    return evaluate


@pytest.mark.asyncio
async def test_well_behaved_run_passes_and_recovers_from_the_injected_failure(evaluate):
    results = await evaluate("reply-flaky-mailbox")

    [run] = results.runs
    assert run.scenario_id == "reply-flaky-mailbox"
    assert run.model == "scripted"
    assert run.status == "completed"
    assert run.final_answer == "I saved a reply to Jan in your Drafts: you'll go through the hours on Tuesday."
    # The tool outputs are kept per call (the contexts for generation metrics).
    search, reply = run.tool_calls
    assert (search.name, search.status) == ("ms365_list-mail-messages", "success")  # retried past the 503
    assert "Questions about invoice 2026-031" in search.output
    assert (reply.name, reply.status) == ("ms365_create-reply-draft", "success")
    assert [i.decision for i in run.interrupts] == ["approve"]
    assert "ms365_create-reply-draft" in run.interrupts[0].actions
    [draft] = run.drafts
    assert draft["subject"] == "RE: Questions about invoice 2026-031"

    score = run.trajectory
    assert (score.precision, score.recall) == (1.0, 1.0)
    assert score.ordering_met is True
    assert score.forbidden_violations == []
    assert score.recovered is True
    assert score.passed is True
    assert run.answer_facts.missing == []


@pytest.mark.asyncio
async def test_wrong_trajectory_fails_with_the_reasons_scored(evaluate):
    results = await evaluate("overdue-reminders-rejected")

    [run] = results.runs
    assert run.status == "completed"
    assert [(c.name, c.status) for c in run.tool_calls] == [
        ("create_draft_email", "rejected"),
        ("ms365_create-draft-email", "rejected"),
    ]
    assert [i.decision for i in run.interrupts] == ["reject", "reject"]
    assert run.drafts == []  # rejected: nothing reached Outlook

    score = run.trajectory
    assert score.precision == 0.5  # the Gmail call was not required
    assert score.recall == 0.5  # Informer was never read
    assert [(o.before, o.after, o.met) for o in score.ordering] == [
        ("informer_list_overdue_invoices", "ms365_create-draft-email", False),
    ]
    assert score.ordering_met is False
    assert score.forbidden_violations == ["create_draft_email"]
    assert score.recovered is None  # no failure injected
    assert score.passed is False
    assert run.answer_facts.missing == ["Noordzee Advies"]


@pytest.mark.asyncio
async def test_summary_aggregates_both_runs(evaluate):
    results = await evaluate()

    assert [r.scenario_id for r in results.runs] == ["reply-flaky-mailbox", "overdue-reminders-rejected"]
    summary = results.summary
    assert (summary.runs, summary.passed, summary.pass_rate) == (2, 1, 0.5)
    assert summary.mean_precision == 0.75
    assert summary.mean_recall == 0.75
    assert summary.ordering_met_rate == 0.5
    assert summary.forbidden_violations == 1
    assert summary.recovery_rate == 1.0  # the one run with an injected failure recovered
    assert summary.facts_rate == 2 / 3
    assert results.model == "scripted"
    assert results.dataset_version == "test-2026-10-07"


@pytest.mark.asyncio
async def test_each_run_records_its_tokens_cost_and_latency(evaluate):
    results = await evaluate("reply-flaky-mailbox")

    [run] = results.runs
    e = run.efficiency
    assert (e.input_tokens, e.output_tokens, e.total_tokens) == (3000, 300, 3300)  # three model calls
    assert e.cost_usd == pytest.approx(0.009)  # 3000 × $2 + 300 × $10, per 1M tokens
    assert e.by_model["claude-sonnet-5-5"].input_tokens == 3000
    assert e.latency_s > 0


@pytest.mark.asyncio
async def test_summary_totals_tokens_and_cost(evaluate):
    results = await evaluate()

    s = results.summary
    assert s.total_tokens == 6600
    assert s.total_cost_usd == pytest.approx(0.018)
    assert s.mean_latency_s > 0


# --- repeats -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repeats_run_each_scenario_again_and_record_each_runs_variation(scripted_model, tmp_path):
    # The first repeat plays the well-behaved script; the second gives up without a tool call.
    scripts = iter([SCRIPTS["reply-flaky-mailbox"], [_answer("I could not find that mail.")]])

    results = await run_eval(load_dataset(DATASET), model_name="scripted",
                             model_factory=lambda scenario: scripted_model(next(scripts)),
                             scenario_filter="reply", repeats=2)

    assert results.repeats == 2
    assert [(r.scenario_id, r.repeat) for r in results.runs] == [("reply-flaky-mailbox", 0), ("reply-flaky-mailbox", 1)]
    assert [r.trajectory.passed for r in results.runs] == [True, False]
    assert results.summary.runs == 2
    assert results.summary.pass_rate == 0.5
    _, report_path = write_results(results, tmp_path)
    report = report_path.read_text()
    assert "| reply-flaky-mailbox #1 | PASS |" in report
    assert "| reply-flaky-mailbox #2 | FAIL |" in report


@pytest.mark.asyncio
async def test_by_default_each_scenario_runs_once(evaluate):
    results = await evaluate()

    assert results.repeats == 1
    assert [r.repeat for r in results.runs] == [0, 0]


@pytest.mark.asyncio
async def test_command_runs_the_given_number_of_repeats(scripted_model, tmp_path, langfuse_spans):
    await main(["--model", "anthropic:claude-sonnet-5-5", "--dataset", str(DATASET), "--scenario", "reply",
                "--repeats", "3", "--out", str(tmp_path), "--no-ragas"],
               create_model=lambda name: scripted_model(itertools.repeat(_answer("Nothing found."))))

    [json_path] = tmp_path.glob("*.json")
    results = EvalResults.model_validate_json(json_path.read_text())
    assert results.repeats == 3
    assert [r.repeat for r in results.runs] == [0, 1, 2]


@pytest.mark.asyncio
async def test_eval_runs_write_nothing_to_the_owners_memory(evaluate, monkeypatch):
    from agent.memory.episodic import EpisodicMemory
    from agent.memory.semantic import SemanticMemory

    written = []
    monkeypatch.setattr(EpisodicMemory, "log_run", lambda self, run: written.append(run))
    monkeypatch.setattr(SemanticMemory, "ingest_interaction", lambda self, *a, **k: written.append(a))

    await evaluate("reply-flaky-mailbox")

    assert written == []


@pytest.mark.asyncio
async def test_the_model_under_test_is_told_the_fixture_worlds_date(scripted_model, monkeypatch):
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2027-01-01")  # an eval ignores the knob: always the seeded date
    seen = []

    def reply(messages):
        seen.append(messages[0].content)
        return _answer("Nothing to do.")

    await run_eval(load_dataset(DATASET), model_name="scripted",
                   model_factory=lambda scenario: scripted_model([reply]), scenario_filter="reply")

    assert "Current date/time: 2026-10-07T09:00:00+02:00" in seen[0]


@pytest.mark.asyncio
async def test_usage_from_a_model_without_a_price_has_no_cost(scripted_model):
    unpriced = [AIMessage(content="Nothing to do.", usage_metadata=USAGE, response_metadata={"model_name": "gpt-9"})]
    results = await run_eval(load_dataset(DATASET), model_name="scripted",
                             model_factory=lambda scenario: scripted_model(unpriced),
                             scenario_filter="reply")

    [run] = results.runs
    assert run.efficiency.total_tokens == 1100
    assert run.efficiency.cost_usd is None
    assert results.summary.total_cost_usd is None  # a total over an unpriced run would understate


# --- generation metrics (RAGAS) with a scripted judge ----------------------------------------
#
# The judge answers each RAGAS prompt by the output schema the prompt asks for, so the real
# RAGAS metrics run on it. The expected scores follow from its verdicts:
# - faithfulness: two statements, the first supported → 0.5
# - answer relevancy: the question it infers embeds at cosine 0.6 to the input → 0.6
# - context precision: only the second context (the reply Draft) is useful → 1/2 at rank 2 → 0.5
# - context recall: the first expected fact is attributed to the contexts, the second not → 0.5

INFERRED_QUESTION = "Did you save a reply to Jan?"


def _judge_reply(messages) -> AIMessage:
    prompt = messages[-1].content
    task = prompt.rpartition("Now perform the same with the following input")[2]
    if '"title": "StatementGeneratorOutput"' in prompt:
        out = {"statements": ["A reply to Jan is saved in Drafts.", "The hours are on Wednesday."]}
    elif '"title": "NLIStatementOutput"' in prompt:
        out = {"statements": [
            {"statement": "A reply to Jan is saved in Drafts.", "reason": "draft created", "verdict": 1},
            {"statement": "The hours are on Wednesday.", "reason": "not in context", "verdict": 0},
        ]}
    elif '"title": "AnswerRelevanceOutput"' in prompt:
        out = {"question": INFERRED_QUESTION, "noncommittal": 0}
    elif '"title": "ContextPrecisionOutput"' in prompt:
        out = {"reason": "-", "verdict": int("AAMkAGZpeHR1cmUADRAFT01" in task)}  # the reply Draft's id
    elif '"title": "ContextRecallOutput"' in prompt:
        out = {"classifications": [
            {"statement": "Tuesday", "reason": "in the reply", "attributed": 1},
            {"statement": "Drafts", "reason": "not stated", "attributed": 0},
        ]}
    else:
        raise AssertionError(f"unexpected judge prompt: {prompt[:200]}")
    return AIMessage(content=f"```json\n{json.dumps(out)}\n```")  # fenced, as models often reply


class ScriptedEmbeddings(Embeddings):
    """Embeds the judge's inferred question at cosine 0.6 to anything else (the scenario input)."""
    VECTORS = {INFERRED_QUESTION: [0.6, 0.8]}

    def embed_query(self, text):
        return self.VECTORS.get(text, [1.0, 0.0])

    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]


@pytest.fixture
def judge(scripted_model):
    return scripted_model(itertools.repeat(_judge_reply))


@pytest.fixture
def evaluate_with_judge(scripted_model, judge):
    async def evaluate(scenario_filter=None):
        return await run_eval(
            load_dataset(DATASET),
            model_name="scripted",
            model_factory=lambda scenario: scripted_model(SCRIPTS[scenario.id]),
            scenario_filter=scenario_filter,
            scorer=RagasScorer(judge=judge, embeddings=ScriptedEmbeddings()),
            judge_model="scripted-judge",
        )
    return evaluate


@pytest.mark.asyncio
async def test_ragas_scores_the_answer_against_the_tool_outputs_with_the_judge(evaluate_with_judge):
    results = await evaluate_with_judge("reply-flaky-mailbox")

    [run] = results.runs
    g = run.generation
    assert g.faithfulness == pytest.approx(0.5)
    assert g.answer_relevancy == pytest.approx(0.6)
    assert g.context_precision == pytest.approx(0.5)
    assert g.context_recall == pytest.approx(0.5)
    assert g.contexts == 2  # the two successful tool calls' outputs
    assert g.notes == {}


@pytest.mark.asyncio
async def test_metrics_without_contexts_are_not_scored_and_say_why(evaluate_with_judge):
    results = await evaluate_with_judge("overdue-reminders-rejected")

    [run] = results.runs
    g = run.generation
    assert g.answer_relevancy == pytest.approx(0.6)  # needs only the question and the answer
    assert (g.faithfulness, g.context_precision, g.context_recall) == (None, None, None)
    assert g.contexts == 0
    assert set(g.notes) == {"faithfulness", "context_precision", "context_recall"}
    assert "no successful tool output" in g.notes["faithfulness"]


@pytest.mark.asyncio
async def test_summary_averages_generation_metrics_over_scored_runs(evaluate_with_judge):
    results = await evaluate_with_judge()

    s = results.summary
    assert s.mean_faithfulness == pytest.approx(0.5)  # only the reply run had contexts
    assert s.mean_answer_relevancy == pytest.approx(0.6)
    assert s.mean_context_precision == pytest.approx(0.5)
    assert s.mean_context_recall == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_a_judge_failure_is_recorded_not_raised(scripted_model):
    garbled = scripted_model(itertools.repeat(lambda messages: AIMessage(content="I cannot answer that.")))
    results = await run_eval(
        load_dataset(DATASET),
        model_name="scripted",
        model_factory=lambda scenario: scripted_model(SCRIPTS[scenario.id]),
        scenario_filter="reply",
        scorer=RagasScorer(judge=garbled, embeddings=ScriptedEmbeddings()),
    )

    [run] = results.runs
    assert run.status == "completed"
    g = run.generation
    assert (g.faithfulness, g.answer_relevancy, g.context_precision, g.context_recall) == (None,) * 4
    assert "judge reply is not valid JSON" in g.notes["faithfulness"]


@pytest.mark.asyncio
async def test_without_a_scorer_generation_is_not_scored(evaluate, tmp_path):
    results = await evaluate("reply")

    assert results.runs[0].generation is None
    assert results.summary.mean_faithfulness is None
    assert results.judge_model is None
    _, report_path = write_results(results, tmp_path)
    assert "Not scored: the eval ran without a judge model." in report_path.read_text()


@pytest.mark.asyncio
async def test_report_shows_the_judge_and_the_generation_scores(evaluate_with_judge, tmp_path):
    results = await evaluate_with_judge()

    json_path, report_path = write_results(results, tmp_path)

    assert EvalResults.model_validate_json(json_path.read_text()) == results
    report = report_path.read_text()
    assert "- Judge model: `scripted-judge`" in report
    assert "## Generation (RAGAS)" in report
    assert "| Faithfulness (mean) | 0.50 |" in report
    assert "| Answer relevancy (mean) | 0.60 |" in report
    assert "| reply-flaky-mailbox | 0.50 | 0.60 | 0.50 | 0.50 | 2 |" in report
    assert "| overdue-reminders-rejected | n/a | 0.60 | n/a | n/a | 0 |" in report


# --- Langfuse tagging ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_run_is_one_langfuse_trace_tagged_with_model_prompt_scenario_and_eval_run(
        scripted_model, langfuse_spans):
    from agent.config import settings
    from agent.tracing import langfuse_trace

    results = await run_eval(
        load_dataset(DATASET),
        model_name="anthropic:claude-sonnet-5-5",
        model_factory=lambda scenario: scripted_model(SCRIPTS[scenario.id]),
        scenario_filter="reply",
        tracer=langfuse_trace,
    )

    [run] = results.runs
    spans = [s for s in langfuse_spans() if f"{s.context.trace_id:032x}" == run.trace_id]
    # One trace spans the whole run, before and after the approval prompt.
    assert {"ms365_list-mail-messages", "ms365_create-reply-draft"} <= {s.name for s in spans}
    for span in spans:
        attributes = span.attributes
        assert set(attributes["langfuse.trace.tags"]) == {
            "eval",
            "model:anthropic:claude-sonnet-5-5",
            f"prompt:{settings.prompt_version}",
            "scenario:reply-flaky-mailbox",
            f"eval-run:{results.eval_run_id}",
        }
        assert attributes["langfuse.trace.name"] == "eval:reply-flaky-mailbox"
        assert attributes["session.id"] == results.eval_run_id  # groups the eval run's traces
        assert attributes["langfuse.trace.metadata.eval_run_id"] == results.eval_run_id
        assert attributes["langfuse.trace.metadata.scenario"] == "reply-flaky-mailbox"
        assert attributes["langfuse.trace.metadata.model"] == "anthropic:claude-sonnet-5-5"
        assert attributes["langfuse.trace.metadata.prompt_version"] == settings.prompt_version


@pytest.mark.asyncio
async def test_without_a_tracer_runs_have_no_trace(evaluate):
    results = await evaluate("reply")

    assert results.runs[0].trace_id is None


# --- results JSON and report ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_results_json_and_report_are_written_side_by_side(evaluate, tmp_path):
    results = await evaluate()

    json_path, report_path = write_results(results, tmp_path)

    assert json_path.parent == report_path.parent == tmp_path
    assert (json_path.stem, json_path.suffix, report_path.suffix) == (results.eval_run_id, ".json", ".md")
    assert EvalResults.model_validate_json(json_path.read_text()) == results  # re-analysable as written

    report = report_path.read_text()
    assert "Model: `scripted`" in report
    assert "| Passed | 1/2 (50%) |" in report
    assert "| Recovery after injected failure | 100% |" in report
    assert "| reply-flaky-mailbox | PASS |" in report
    assert "| overdue-reminders-rejected | FAIL |" in report
    # A failing run says why.
    assert "missing required tools: informer_list_overdue_invoices" in report
    assert "ordering not met: informer_list_overdue_invoices before ms365_create-draft-email" in report
    assert "forbidden tools called: create_draft_email" in report
    # Efficiency: totals in the summary, tokens and cost per scenario run.
    assert "| Total tokens | 6600 |" in report
    assert "| Total cost | $0.0180 |" in report
    assert "| Mean latency |" in report
    assert "## Efficiency" in report
    assert "| reply-flaky-mailbox | 3000 | 300 | $0.0090 |" in report


# --- the command ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_command_runs_the_chosen_model_on_filtered_scenarios_and_writes_both_files(
        scripted_model, tmp_path, capsys, langfuse_spans):
    chosen = []

    def create_model(name):
        chosen.append(name)
        return scripted_model(SCRIPTS["reply-flaky-mailbox"])

    await main(["--model", "anthropic:claude-sonnet-5-5", "--dataset", str(DATASET), "--scenario", "reply",
                "--out", str(tmp_path), "--no-ragas"], create_model=create_model)

    assert chosen == ["anthropic:claude-sonnet-5-5"]  # --no-ragas: no judge
    [json_path] = tmp_path.glob("*.json")
    results = EvalResults.model_validate_json(json_path.read_text())
    assert [r.scenario_id for r in results.runs] == ["reply-flaky-mailbox"]
    assert results.model == "anthropic:claude-sonnet-5-5"
    assert results.judge_model is None
    assert results.runs[0].generation is None
    assert json_path.with_suffix(".md").exists()
    out = capsys.readouterr().out
    assert "1/1 passed" in out
    assert str(json_path) in out


@pytest.fixture
def models(scripted_model):
    """create_model for the command: the model under test plays its script, the judge judges."""
    chosen = []

    def create_model(name):
        chosen.append(name)
        if len(chosen) == 1:
            return scripted_model(SCRIPTS["reply-flaky-mailbox"])
        return scripted_model(itertools.repeat(_judge_reply))
    create_model.chosen = chosen
    return create_model


@pytest.mark.asyncio
async def test_command_grades_answers_with_the_judge_model_and_traces_each_run(
        models, tmp_path, capsys, langfuse_spans):
    await main(["--model", "google_genai:gemini-3.8-flash", "--judge-model", "anthropic:claude-sonnet-5-5",
                "--dataset", str(DATASET), "--scenario", "reply", "--out", str(tmp_path)],
               create_model=models, create_embeddings=ScriptedEmbeddings)

    assert models.chosen == ["google_genai:gemini-3.8-flash", "anthropic:claude-sonnet-5-5"]
    [json_path] = tmp_path.glob("*.json")
    results = EvalResults.model_validate_json(json_path.read_text())
    assert results.judge_model == "anthropic:claude-sonnet-5-5"
    [run] = results.runs
    assert run.generation.faithfulness == pytest.approx(0.5)
    assert run.trace_id in {f"{s.context.trace_id:032x}" for s in langfuse_spans()}
    assert "grades its own answers" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_without_a_judge_model_the_model_under_test_grades_and_the_command_says_so(
        models, tmp_path, capsys, langfuse_spans, monkeypatch):
    from agent.config import settings
    monkeypatch.setattr(settings, "eval_judge_model", None)

    await main(["--model", "google_genai:gemini-3.8-flash", "--dataset", str(DATASET), "--scenario", "reply",
                "--out", str(tmp_path)], create_model=models, create_embeddings=ScriptedEmbeddings)

    assert models.chosen == ["google_genai:gemini-3.8-flash"] * 2
    assert "google_genai:gemini-3.8-flash grades its own answers" in capsys.readouterr().out
    [report_path] = tmp_path.glob("*.md")
    assert "(the model under test: it grades its own answers)" in report_path.read_text()


@pytest.mark.asyncio
async def test_the_judge_model_defaults_to_the_setting(models, tmp_path, langfuse_spans, monkeypatch):
    from agent.config import settings
    monkeypatch.setattr(settings, "eval_judge_model", "anthropic:claude-sonnet-5-5")

    await main(["--model", "google_genai:gemini-3.8-flash", "--dataset", str(DATASET), "--scenario", "reply",
                "--out", str(tmp_path)], create_model=models, create_embeddings=ScriptedEmbeddings)

    assert models.chosen == ["google_genai:gemini-3.8-flash", "anthropic:claude-sonnet-5-5"]


def test_shipped_dataset_loads():
    assert load_dataset().scenarios
