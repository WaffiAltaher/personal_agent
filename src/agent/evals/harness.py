# src/agent/evals/harness.py
"""Runs scenarios through the agent graph against the Fixture world and scores them.

Each scenario run gets a fresh Fixture world: the clock pinned to the seeded date (which the
model is told as "today" too), its own Drafts file, its own drive (seeded like the stand-in's,
EVAL_SEEDED_DRIVE), its own Informer upload log (seeded with the scenario's `informer_uploads`),
and the scenario's injected failure. The
tools are loaded as `--fixtures` loads them, the chat model is injected into the graph, and
every approval prompt is answered with the scenario's approval policy through
`run_conversation`, as the CLI does with the owner's answer.

Every scenario gets the same tools the agent has in production, so the model chooses among
all of them, as it does for the owner. None of them touches anything real: the MCP servers, web
search, Gmail and Google Calendar are the Fixture world's stand-ins; the file tools are confined
to the run's own Downloads folder; and episodic and semantic memory are temporary stores (the
episodic one seeded from EVAL_EPISODIC_SEED). The agent folder, where attachments are saved, is
the run's own `Downloads/personal_agent`, inside the Downloads folder the Informer upload accepts.
"""

import json
import os
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import agent.memory as memory_module
from agent.memory.episodic import EpisodicMemory, RunRecord

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from agent.config import settings
from agent.evals.efficiency import efficiency, efficiency_totals
from agent.evals.generation import GenerationScorer, RagasScorer, generation_means, generation_sample
from agent.evals.records import EvalResults, InterruptRecord, RunResult, ToolCallRecord
from agent.evals.report import render_report
from agent.evals.scenarios import Dataset, Scenario
from agent.evals.outcome import read_agent_folder, run_passed, score_outcome
from agent.evals.trajectory import score_facts, score_trajectory, summarise
from agent.conversation import run_conversation
from agent.graph import build_graph, is_step_limit_answer
from agent.tracing import TraceAttributes
from agent.memory import fixtures_semantic_memory
from agent.tools import load_all_tools
from agent.tools.classification import action_class, classify_as, is_outbound_read
from agent.tools.filesystem import (
    FILES_ROOT_ENV,
    fixture_list_directory,
    fixture_read_file,
    list_directory,
    read_file,
)
from agent.tools.pdf_text import fixture_read_pdf_text, read_pdf_text
from fixture_world import clock, informer as fixture_informer, ms365 as fixture_ms365
from fixture_world.pdfs import no_text_pdf, text_pdf
from informer_mcp.purchase_upload import fingerprint

# Backstop only: the graph's model-call counter enforces settings.max_iterations.
RECURSION_LIMIT = max(settings.max_iterations * 5 + 10, 40)

EVAL_EPISODIC_SEED = Path(__file__).parent / "fixtures" / "episodic_seed.json"
EVAL_SEEDED_DRIVE = files("fixture_world") / "data" / "ms365" / "drive"  # each run's drive starts as this
EVAL_ARCHIVE = "Documents/ittopia/admin"
EVAL_DOWNLOAD_PDFS: dict[str, bytes] = {
    "supplier-march.pdf": b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
    "fail-me.pdf": b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
    # A Purchase invoice with its invoice date printed in its text layer, and a scan with none.
    "kpn-factuur-123456.pdf": text_pdf([
        "KPN B.V.", "Factuur", "Factuurnummer: 123456", "Factuurdatum: 14-10-2026",
        "Totaal te betalen: EUR 48,40",
    ]),
    "scan-factuur.pdf": no_text_pdf(),
    # A Purchase invoice that is nowhere yet: not in the Invoice archive, not uploaded to Informer.
    "hosting-2026-10.pdf": text_pdf([
        "Hosting Noord B.V.", "Factuur", "Factuurnummer: HN-2026-10", "Factuurdatum: 05-10-2026",
        "Totaal te betalen: EUR 60,50",
    ]),
    # Copies of invoices the stand-in's drive is seeded with: the same contents under another name,
    # and under the same name. (kpn-factuur-123456.pdf above is deliberately a different file under
    # a name the drive holds too: the name clash with different contents.)
    "kpn-oktober.pdf": (EVAL_SEEDED_DRIVE / EVAL_ARCHIVE / "2026" / "October" / "kpn-factuur-123456.pdf").read_bytes(),
    "Factuur.pdf": (EVAL_SEEDED_DRIVE / EVAL_ARCHIVE / "2026" / "September" / "Factuur.pdf").read_bytes(),
}


def _scenario_user_message(scenario: Scenario, downloads_path: Path) -> str:
    """Include the eval Downloads path for every upload and invoice archive scenario, including
    reject and failure."""
    if scenario.workflow in ("upload", "invoice archive"):
        return f"{scenario.input}\n\n(Downloads folder: {downloads_path})"
    return scenario.input


def _seed_eval_downloads(downloads_path: Path) -> None:
    downloads_path.mkdir(parents=True, exist_ok=True)
    for name, data in EVAL_DOWNLOAD_PDFS.items():
        (downloads_path / name).write_bytes(data)


@contextmanager
def _isolated_eval_episodic(workdir: Path) -> Iterator[None]:
    """Point episodic memory at a temp DB seeded with the eval run history; restore after."""
    prev = memory_module._episodic
    mem = EpisodicMemory(db_path=str(workdir / "episodic.db"))
    for row in json.loads(EVAL_EPISODIC_SEED.read_text()):
        mem.log_run(RunRecord(**row))
    memory_module._episodic = mem
    try:
        yield
    finally:
        mem.close()
        memory_module._episodic = prev

# The real file tools read the owner's disk even in Fixture-world mode; an eval binds stand-ins
# confined to the run's Downloads folder under the same names instead.
EVAL_FILE_STAND_INS = {
    read_file.name: fixture_read_file,
    list_directory.name: fixture_list_directory,
    read_pdf_text.name: fixture_read_pdf_text,
}

ModelFactory = Callable[[Scenario], BaseChatModel]
ToolLoader = Callable[[], Awaitable[tuple[list[BaseTool], list[str]]]]
# Opens one trace for a scenario run and yields the callbacks that record into it, e.g.
# agent.tracing.langfuse_trace.
Tracer = Callable[[TraceAttributes], AbstractContextManager[list]]


def trace_attributes(scenario: Scenario, *, model_name: str, eval_run_id: str, repeat: int) -> TraceAttributes:
    """What a scenario run's trace is tagged with, so a score can be traced back to its trace:
    the model, prompt version, scenario and eval run, as tags and as metadata; the eval run is
    also the session that groups its traces."""
    return TraceAttributes(
        trace_id=uuid.uuid4().hex,
        name=f"eval:{scenario.id}",
        session_id=eval_run_id,
        tags=["eval", f"model:{model_name}", f"prompt:{settings.prompt_version}",
              f"scenario:{scenario.id}", f"eval-run:{eval_run_id}"],
        metadata={"model": model_name, "prompt_version": settings.prompt_version, "scenario": scenario.id,
                  "eval_run_id": eval_run_id, "repeat": str(repeat)},
    )


async def load_fixture_world_tools() -> tuple[list[BaseTool], list[str]]:
    """Every tool `--fixtures` loads, with the file tools swapped for EVAL_FILE_STAND_INS (same
    classification), and any notices."""
    tools, notices = await load_all_tools(fixtures=True)
    return [
        classify_as(EVAL_FILE_STAND_INS[t.name], action_class(t)) if t.name in EVAL_FILE_STAND_INS else t
        for t in tools
    ], notices


@contextmanager
def _environment(values: dict[str, str | None]) -> Iterator[None]:
    """Set (or, for None, unset) environment variables for the block, then restore them."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _agent_folder(folder: Path, downloads: Path) -> Iterator[None]:
    """Point the agent folder setting at `folder`, and the Downloads folder the Invoice archive tools
    accept at `downloads`, for the block, then restore them."""
    saved = settings.agent_folder, settings.informer_downloads_dir
    settings.agent_folder, settings.informer_downloads_dir = str(folder), str(downloads)
    try:
        yield
    finally:
        settings.agent_folder, settings.informer_downloads_dir = saved


def _seed_informer_uploads(log: Path, uploads: dict[str, str], downloads: Path) -> None:
    """Write the Informer upload log as if each eval Downloads file had been uploaded on its date."""
    with log.open("a") as f:
        for name, uploaded_on in uploads.items():
            f.write(json.dumps({"fingerprint": fingerprint((downloads / name).read_bytes()),
                                "date": uploaded_on}) + "\n")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in content
                       if isinstance(b, str) or (isinstance(b, dict) and b.get("type") == "text"))
    return str(content)


def _tool_call_records(messages: list, rejected: set[str]) -> list[ToolCallRecord]:
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    records = []
    step = 0
    for message in messages:
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        step += 1
        for call in message.tool_calls:
            result = results.get(call["id"])
            if call["id"] in rejected:
                status = "rejected"
            elif result is None:
                status = "not_run"
            else:
                status = "error" if result.status == "error" else "success"
            records.append(ToolCallRecord(
                id=call["id"],
                name=call["name"],
                args=call.get("args", {}),
                step=step,
                status=status,
                output=_text(result.content) if result is not None else "",
            ))
    return records


def _final_answer(messages: list) -> str:
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and not last.tool_calls:
        return _text(last.content)
    return ""


async def run_scenario(
    scenario: Scenario,
    *,
    model: BaseChatModel,
    model_name: str,
    load_tools: ToolLoader = load_fixture_world_tools,
    repeat: int = 0,
    scorer: GenerationScorer | None = None,
    tracer: Tracer | None = None,
    eval_run_id: str = "",
    judge_model: str | None = None,
) -> RunResult:
    """Run one scenario in a fresh Fixture world and score it. Never raises for agent failures:
    a crash or the step limit is recorded in the result's status. With a `scorer`, the final
    answer also gets generation metrics (RAGAS); with a `tracer`, the run is one tagged trace."""
    failure = scenario.inject_failure
    sent: list[dict] = []
    upload_log_path_str: str | None = None
    expected_bytes: dict[str, bytes] | None = None
    saved: dict[str, bytes] = {}
    archived: dict[str, bytes] = {}
    expected_archive: dict[str, bytes | None] | None = None
    with tempfile.TemporaryDirectory(prefix="eval-") as workdir:
        work = Path(workdir)
        drafts_path = work / "drafts.jsonl"
        sent_path = work / "sent.jsonl"
        downloads_path = work / "Downloads"
        _seed_eval_downloads(downloads_path)
        agent_folder = downloads_path / "personal_agent"
        switch = fixture_ms365.FailureSwitch(Path(workdir) / "ms365-failure")
        drive_path = work / "drive"  # seeded from EVAL_SEEDED_DRIVE on first use; nothing carries over
        upload_log = work / "informer-uploads.jsonl"  # no uploads carry over between runs
        _seed_informer_uploads(upload_log, scenario.informer_uploads, downloads_path)
        env = {
            clock.TODAY_ENV: clock.SEED_TODAY.isoformat(),
            fixture_ms365.DRAFTS_ENV: str(drafts_path),
            fixture_informer.UPLOAD_LOG_ENV: str(upload_log),
            fixture_ms365.DRIVE_ENV: str(drive_path),
            fixture_ms365.DRIVE_FAILURE_ENV: failure.mode if failure and failure.server == "drive" else None,
            fixture_ms365.DRAFT_FAILURE_ENV: None,
            fixture_ms365.SENT_ENV: str(sent_path),
            fixture_ms365.FAILURE_ENV: None,
            **switch.env,
            # The Informer stand-in reads its failure mode at each tool call's process start.
            fixture_informer.FAILURE_ENV: failure.mode if failure and failure.server == "informer" else None,
            fixture_informer.DOWNLOADS_ENV: str(downloads_path),  # the server process only sees FIXTURE_WORLD_* vars
            "INFORMER_DOWNLOADS_DIR": str(downloads_path),
            FILES_ROOT_ENV: str(downloads_path),  # the file tools see only the run's Downloads folder
            # The MS365 stand-in the Informer server sends through reads it at each upload.
            fixture_ms365.SEND_FAILURE_ENV: failure.mode if failure and failure.server == "handover" else None,
        }
        with (_isolated_eval_episodic(work), fixtures_semantic_memory(), _environment(env),
              _agent_folder(agent_folder, downloads_path)):
            seeded = set(fixture_ms365.archived_files(fixture_ms365.drive_path()))  # drive_path() seeds it
            tools, notices = await load_tools()
            if failure and failure.server == "ms365":
                switch.set(failure.mode, failure.times)  # after loading: it hits the run, not startup

            graph = build_graph(checkpointer=InMemorySaver(), tools=tools, model=model, today=clock.today())
            trace = trace_attributes(scenario, model_name=model_name, eval_run_id=eval_run_id, repeat=repeat)
            usage = UsageMetadataCallbackHandler()
            interrupts: list[InterruptRecord] = []
            rejected: set[str] = set()
            status, error = "completed", None
            with tracer(trace) if tracer else nullcontext([]) as trace_callbacks:
                config = {
                    "configurable": {"thread_id": f"eval-{scenario.id}-{repeat}-{uuid.uuid4().hex[:8]}"},
                    "recursion_limit": RECURSION_LIMIT,
                    "callbacks": [usage, *trace_callbacks],
                }
                started = time.perf_counter()
                try:
                    result = await run_conversation(
                        graph,
                        config,
                        tools=tools,
                        user_message=_scenario_user_message(scenario, downloads_path),
                        today=clock.today(),
                    )
                    while "__interrupt__" in result:
                        for pending in result["__interrupt__"]:
                            interrupts.append(InterruptRecord(actions=pending.value.get("actions", ""),
                                                              decision=scenario.approval))
                            if scenario.approval == "reject":
                                # The calls this Approval covers: Write actions and gated Outbound reads.
                                rejected |= set(pending.value.get("tool_call_ids", []))
                        result = await run_conversation(
                            graph, config, tools=tools, resume_decision=scenario.approval,
                        )
                except GraphRecursionError:
                    status = "step_limit"
                except Exception as exc:  # an eval records a crashing run instead of stopping
                    status, error = "error", f"{type(exc).__name__}: {exc}"
                latency_s = time.perf_counter() - started

            # The checkpointed state holds the messages so far, also after a crash.
            messages = (await graph.aget_state(config)).values.get("messages", [])
            drafts = fixture_ms365.recorded_drafts(drafts_path)
            sent = fixture_ms365.sent_messages(sent_path)
            upload_log_path_str = str(sent_path)
            saved = read_agent_folder(agent_folder)
            archived = {path: data for path, data in fixture_ms365.archived_files(drive_path).items()
                        if path not in seeded}
            if scenario.expected_outcome and scenario.expected_outcome.archived_files:
                expected_archive = {
                    path: (downloads_path / name).read_bytes() if (downloads_path / name).is_file() else None
                    for path, name in scenario.expected_outcome.archived_files.items()
                }
            if scenario.expected_outcome and scenario.expected_outcome.upload_file:
                upload_name = scenario.expected_outcome.upload_file
                # A file the run saved into the agent folder is uploaded from there, wherever the
                # prompt says that folder is.
                saved_as = [p for p in (scenario.expected_outcome.saved_files or []) if Path(p).name == upload_name]
                candidate = agent_folder / saved_as[0] if saved_as else downloads_path / upload_name
                expected_bytes = (
                    {upload_name: candidate.read_bytes()} if candidate.is_file() else {upload_name: None}
                )

    if is_step_limit_answer(messages[-1] if messages else None):
        status = "step_limit"

    tool_calls = _tool_call_records(messages, rejected)
    final_answer = _final_answer(messages) if status == "completed" else ""
    trajectory = score_trajectory(scenario, tool_calls, completed=status == "completed" and bool(final_answer))
    outcome = score_outcome(
        scenario,
        sent,
        final_answer=final_answer,
        expected_bytes=expected_bytes,
        saved=saved,
        approvals=len(interrupts),
        tool_calls=tool_calls,
        outbound_tools=frozenset(t.name for t in tools if is_outbound_read(t)),
        archived=archived,
        expected_archive=expected_archive,
    )
    run = RunResult(
        scenario_id=scenario.id,
        workflow=scenario.workflow,
        repeat=repeat,
        model=model_name,
        input=scenario.input,
        status=status,
        error=error,
        final_answer=final_answer,
        tool_calls=tool_calls,
        interrupts=interrupts,
        notices=notices,
        drafts=drafts,
        trajectory=trajectory,
        outcome=outcome,
        answer_facts=score_facts(scenario, final_answer),
        passed=run_passed(scenario, trajectory, outcome, final_answer=final_answer),
        upload_log_path=upload_log_path_str,
        efficiency=efficiency(usage.usage_metadata, latency_s=latency_s, on=datetime.now(timezone.utc).date()),
        trace_id=trace.trace_id if tracer else None,
    )
    if scorer is not None:
        if isinstance(scorer, RagasScorer) and judge_model:
            scorer.begin_scenario_run(
                eval_run_id=eval_run_id,
                scenario_id=scenario.id,
                repeat=repeat,
                judge_model=judge_model,
            )
        run.generation = await scorer.score(generation_sample(scenario, run))
    return run


async def run_eval(
    dataset: Dataset,
    *,
    model_name: str,
    model_factory: ModelFactory,
    scenario_filter: str | None = None,
    load_tools: ToolLoader = load_fixture_world_tools,
    dataset_path: Path | str = "",
    scorer: GenerationScorer | None = None,
    judge_model: str | None = None,
    tracer: Tracer | None = None,
    repeats: int = 1,
) -> EvalResults:
    """Run every selected scenario `repeats` times, each run with a fresh model from
    `model_factory` and a fresh Fixture world, and summarise over all runs (a run records
    its repeat, 0-based, so the variation per scenario can be read from the results).
    `scorer` adds generation metrics, graded by `judge_model` (recorded in the results);
    `tracer` traces each run, tagged with the model, prompt version, scenario and eval run."""
    if repeats < 1:
        raise ValueError(f"repeats must be at least 1, not {repeats}")
    started = datetime.now(timezone.utc)
    eval_run_id = f"{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    runs = [
        await run_scenario(
            scenario,
            model=model_factory(scenario),
            model_name=model_name,
            load_tools=load_tools,
            repeat=repeat,
            scorer=scorer,
            tracer=tracer,
            eval_run_id=eval_run_id,
            judge_model=judge_model,
        )
        for scenario in dataset.select(scenario_filter)
        for repeat in range(repeats)
    ]
    return EvalResults(
        eval_run_id=eval_run_id,
        started_at=started.isoformat(),
        model=model_name,
        judge_model=judge_model,
        prompt_version=settings.prompt_version,
        dataset_path=str(dataset_path),
        dataset_version=dataset.dataset_version,
        scenario_filter=scenario_filter,
        repeats=repeats,
        runs=runs,
        summary=summarise(runs).model_copy(update={**efficiency_totals(runs), **generation_means(runs)}),
    )


def write_results(results: EvalResults, out_dir: Path | str) -> tuple[Path, Path]:
    """Write the results JSON and the markdown report side by side, named by the eval-run id."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{results.eval_run_id}.json"
    report_path = out_dir / f"{results.eval_run_id}.md"
    json_path.write_text(results.model_dump_json(indent=2))
    report_path.write_text(render_report(results))
    return json_path, report_path
