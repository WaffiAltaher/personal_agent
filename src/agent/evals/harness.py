# src/agent/evals/harness.py
"""Runs scenarios through the agent graph against the Fixture world and scores them.

Each scenario run gets a fresh Fixture world: the clock pinned to the seeded date (which the
model is told as "today" too), its own Drafts file, and the scenario's injected failure. The
tools are loaded as `--fixtures` loads them, the chat model is injected into the graph, and
every approval prompt is answered with the scenario's approval policy through
`run_conversation`, as the CLI does with the owner's answer.

Only tools that stay inside the Fixture world are bound: the Fixture world's MCP tools plus
the local tools in EVAL_LOCAL_TOOLS (the seeded web search and Gmail stand-ins). The other local
tools reach the owner's real Gmail, Google Calendar, memory store or files, and an auto-approved
Write action there would be real. The agent folder, where attachments are saved, is the run's own
`Downloads/personal_agent`, inside the Downloads folder the Informer upload accepts.
"""

import json
import os
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import datetime, timezone
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
from agent.evals.generation import GenerationScorer, generation_means, generation_sample
from agent.evals.records import EvalResults, InterruptRecord, RunResult, ToolCallRecord
from agent.evals.report import render_report
from agent.evals.scenarios import Dataset, Scenario
from agent.evals.outcome import read_agent_folder, read_upload_log, run_passed, score_outcome
from agent.evals.trajectory import score_facts, score_trajectory, summarise
from fixture_world.purchase_handover import HANDOVER_FAIL_ENV, UPLOAD_LOG_ENV
from agent.conversation import run_conversation
from agent.graph import build_graph, is_step_limit_answer
from agent.tracing import TraceAttributes
from agent.tools import LOCAL_TOOLS, load_all_tools
from agent.tools.classification import is_read
from agent.tools.gmail import get_gmail_message, save_gmail_attachment, search_gmail
from agent.tools.memory import retrieve_episodic_memory
from agent.tools.web import web_search
from fixture_world import clock, informer as fixture_informer, ms365 as fixture_ms365

# Backstop only: the graph's model-call counter enforces settings.max_iterations.
RECURSION_LIMIT = max(settings.max_iterations * 5 + 10, 40)

EVAL_EPISODIC_SEED = Path(__file__).parent / "fixtures" / "episodic_seed.json"
EVAL_DOWNLOAD_PDFS: dict[str, bytes] = {
    "supplier-march.pdf": b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
    "fail-me.pdf": b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
}


def _scenario_user_message(scenario: Scenario, downloads_path: Path) -> str:
    """Include the eval Downloads path for every upload scenario, including reject and failure."""
    if scenario.workflow == "upload":
        return f"{scenario.input}\n\n(Downloads folder: {downloads_path})"
    return scenario.input


def _seed_eval_downloads(downloads_path: Path) -> None:
    downloads_path.mkdir(parents=True, exist_ok=True)
    for name, data in EVAL_DOWNLOAD_PDFS.items():
        (downloads_path / name).write_bytes(data)


@contextmanager
def _isolated_eval_episodic(workdir: Path, scenario: Scenario) -> Iterator[None]:
    """Point episodic memory at a temp DB seeded for memory scenarios; restore after."""
    if scenario.workflow != "memory":
        yield
        return
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

# Local tools that touch nothing real in Fixture-world mode: safe to bind in an eval. (The web
# search and the Gmail tools are the Fixture world's seeded ones there, under the real tools'
# names; the Gmail save writes into the run's agent folder.)
EVAL_LOCAL_TOOLS = frozenset({
    web_search.name,
    retrieve_episodic_memory.name,
    search_gmail.name,
    get_gmail_message.name,
    save_gmail_attachment.name,
})

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
    """The Fixture world's MCP tools plus the local tools in EVAL_LOCAL_TOOLS, and any notices."""
    tools, notices = await load_all_tools(fixtures=True)
    local = {t.name for t in LOCAL_TOOLS}
    return [t for t in tools if t.name not in local or t.name in EVAL_LOCAL_TOOLS], notices


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
def _agent_folder(folder: Path) -> Iterator[None]:
    """Point the agent folder setting at `folder` for the block, then restore it."""
    saved = settings.agent_folder
    settings.agent_folder = str(folder)
    try:
        yield
    finally:
        settings.agent_folder = saved


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
) -> RunResult:
    """Run one scenario in a fresh Fixture world and score it. Never raises for agent failures:
    a crash or the step limit is recorded in the result's status. With a `scorer`, the final
    answer also gets generation metrics (RAGAS); with a `tracer`, the run is one tagged trace."""
    failure = scenario.inject_failure
    recorded_uploads: list[tuple[str, bytes]] = []
    upload_log_path_str: str | None = None
    expected_bytes: dict[str, bytes] | None = None
    saved: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="eval-") as workdir:
        work = Path(workdir)
        drafts_path = work / "drafts.jsonl"
        upload_log_path = work / "purchase-uploads.jsonl"
        downloads_path = work / "Downloads"
        _seed_eval_downloads(downloads_path)
        agent_folder = downloads_path / "personal_agent"
        switch = fixture_ms365.FailureSwitch(Path(workdir) / "ms365-failure")
        env = {
            clock.TODAY_ENV: clock.SEED_TODAY.isoformat(),
            fixture_ms365.DRAFTS_ENV: str(drafts_path),
            fixture_informer.UPLOAD_LOG_ENV: str(Path(workdir) / "informer-uploads.jsonl"),  # no uploads carry over between runs
            fixture_ms365.DRAFT_FAILURE_ENV: None,
            fixture_ms365.FAILURE_ENV: None,
            **switch.env,
            # The Informer stand-in reads its failure mode at each tool call's process start.
            fixture_informer.FAILURE_ENV: failure.mode if failure and failure.server == "informer" else None,
            UPLOAD_LOG_ENV: str(upload_log_path),
            fixture_informer.DOWNLOADS_ENV: str(downloads_path),  # the server process only sees FIXTURE_WORLD_* vars
            "INFORMER_DOWNLOADS_DIR": str(downloads_path),
            HANDOVER_FAIL_ENV: (
                failure.mode
                if failure and failure.server == "handover"
                else os.environ.get(HANDOVER_FAIL_ENV)
            ),
        }
        with _isolated_eval_episodic(work, scenario), _environment(env), _agent_folder(agent_folder):
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
                            tool_by_name = {t.name: t for t in tools}
                            rejected |= {
                                call["id"]
                                for call in result["messages"][-1].tool_calls
                                if tool_by_name.get(call["name"]) is None
                                or not is_read(tool_by_name[call["name"]])
                            }
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
            recorded_uploads = read_upload_log(upload_log_path)
            upload_log_path_str = str(upload_log_path)
            saved = read_agent_folder(agent_folder)
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
        recorded_uploads,
        final_answer=final_answer,
        expected_bytes=expected_bytes,
        saved=saved,
        approvals=len(interrupts),
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
        await run_scenario(scenario, model=model_factory(scenario), model_name=model_name, load_tools=load_tools,
                           repeat=repeat, scorer=scorer, tracer=tracer, eval_run_id=eval_run_id)
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
