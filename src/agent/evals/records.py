# src/agent/evals/records.py
"""What an eval run records: one RunResult per scenario run, inside one EvalResults file.

The results JSON is `EvalResults.model_dump_json()`; `EvalResults.model_validate_json()` reads it
back for re-analysis or a comparison report. Later metrics add fields here (with defaults, so
older results files still load) rather than a second record:
- generation metrics (RAGAS) score `final_answer` against `tool_calls[*].output` as contexts
  and `expected_facts` from the scenario;
- tokens, cost and latency belong on RunResult, their totals on Summary;
- repeats reuse `RunResult.repeat`.
"""

from typing import Literal

from pydantic import BaseModel

RESULTS_FORMAT_VERSION = 1


class ToolCallRecord(BaseModel):
    """One tool call the model made, and what came back."""
    id: str
    name: str
    args: dict
    step: int  # which model turn proposed it (parallel calls share a step)
    status: Literal["success", "error", "rejected", "not_run"]
    output: str  # the tool result the model saw ("" when not run)


class InterruptRecord(BaseModel):
    """An approval prompt, and the scenario's decision on it."""
    actions: str
    decision: Literal["approve", "reject"]


class OrderingResult(BaseModel):
    before: str
    after: str
    met: bool


class TrajectoryScore(BaseModel):
    precision: float  # share of the distinct tools called that were required (1.0 if none called)
    recall: float  # share of the required tools that were called (1.0 if none required)
    missing_tools: list[str]  # required tools that were not called
    extra_tools: list[str]  # tools called that were not required
    ordering: list[OrderingResult]
    ordering_met: bool
    forbidden_violations: list[str]  # forbidden tools that were called (approved or not)
    recovered: bool | None  # None without an injected failure
    passed: bool


class FactsScore(BaseModel):
    """Expected answer facts found in the final answer (case-insensitive substring match)."""
    found: list[str]
    missing: list[str]


class RunResult(BaseModel):
    scenario_id: str
    workflow: str
    repeat: int = 0
    model: str
    input: str
    status: Literal["completed", "step_limit", "error"]
    error: str | None = None
    final_answer: str
    tool_calls: list[ToolCallRecord]
    interrupts: list[InterruptRecord]
    notices: list[str]  # integrations that were unavailable for the run
    drafts: list[dict]  # Drafts the MS365 stand-in recorded during the run
    trajectory: TrajectoryScore
    answer_facts: FactsScore


class Summary(BaseModel):
    runs: int
    passed: int
    pass_rate: float
    mean_precision: float
    mean_recall: float
    ordering_met_rate: float
    forbidden_violations: int  # runs with at least one violation
    recovery_rate: float | None  # over runs with an injected failure; None if there were none
    facts_rate: float  # share of all expected facts found


class EvalResults(BaseModel):
    format_version: int = RESULTS_FORMAT_VERSION
    eval_run_id: str
    started_at: str
    model: str
    prompt_version: str
    dataset_path: str
    dataset_version: str
    scenario_filter: str | None
    runs: list[RunResult]
    summary: Summary
