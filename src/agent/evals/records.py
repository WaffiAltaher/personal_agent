# src/agent/evals/records.py
"""What an eval run records: one RunResult per scenario run, inside one EvalResults file.

The results JSON is `EvalResults.model_dump_json()`; `EvalResults.model_validate_json()` reads it
back for re-analysis or a comparison report. Later metrics add fields here (with defaults, so
older results files still load) rather than a second record:
- generation metrics (RAGAS) score `final_answer` against `tool_calls[*].output` as contexts
  and `expected_facts` from the scenario: `RunResult.generation`, means on Summary;
- tokens, cost and latency: `RunResult.efficiency`, totals on Summary;
- the run's Langfuse trace: `RunResult.trace_id`;
- repeats: `EvalResults.repeats` runs per scenario, each RunResult with its `repeat`.
"""

from typing import Literal

from pydantic import BaseModel, model_validator

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


class OutcomeScore(BaseModel):
    """Whether the run's outcome matched the scenario (uploads, failure reported)."""
    applicable: bool
    passed: bool
    upload_count: int = 0
    uploads: list[str] = []
    detail: str = ""


class ModelUsage(BaseModel):
    """Tokens one model used in a run, as its responses reported them, and their cost."""
    input_tokens: int = 0  # includes cached input
    output_tokens: int = 0  # includes thinking tokens
    total_tokens: int = 0
    cost_usd: float | None = None  # None: model or usage not in the price table (agent/evals/pricing.py)


class Efficiency(BaseModel):
    """Tokens, cost and latency of one scenario run (every model call the agent made in it)."""
    latency_s: float  # wall-clock time from the first input to the final answer, approvals included
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None  # None if any model's usage could not be priced
    by_model: dict[str, ModelUsage] = {}  # keyed by the model name the provider reported


class GenerationScores(BaseModel):
    """RAGAS scores of the final answer (0..1), with the tool outputs as retrieved contexts and
    the scenario's expected facts as the reference. None: not scored, the reason in `notes`."""
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    contexts: int = 0  # how many tool outputs were used as contexts
    notes: dict[str, str] = {}  # metric → why it has no score


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
    outcome: OutcomeScore
    answer_facts: FactsScore
    passed: bool  # trajectory and, when declared, outcome
    upload_log_path: str | None = None  # Fixture-world hand-over log for this run; None outside eval workdirs
    efficiency: Efficiency | None = None
    generation: GenerationScores | None = None  # None: the eval ran without a judge
    trace_id: str | None = None  # the run's Langfuse trace; None: not traced

    @model_validator(mode="before")
    @classmethod
    def _legacy_run_fields(cls, data):
        if not isinstance(data, dict):
            return data
        if "outcome" not in data:
            data["outcome"] = {"applicable": False, "passed": True}
        if "passed" not in data and isinstance(data.get("trajectory"), dict):
            data["passed"] = data["trajectory"].get("passed", False)
        return data


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
    mean_outcome_rate: float | None = None  # mean outcome.passed over runs that declare an expected outcome
    total_tokens: int = 0
    total_cost_usd: float | None = None  # None if any run's cost is unknown
    mean_latency_s: float | None = None
    # Means of the RAGAS scores over the runs that have one; None if none has.
    mean_faithfulness: float | None = None
    mean_answer_relevancy: float | None = None
    mean_context_precision: float | None = None
    mean_context_recall: float | None = None


class EvalResults(BaseModel):
    format_version: int = RESULTS_FORMAT_VERSION
    eval_run_id: str
    started_at: str
    model: str
    judge_model: str | None = None  # grades the generation metrics; None: not scored
    prompt_version: str
    dataset_path: str
    dataset_version: str
    scenario_filter: str | None
    repeats: int = 1  # runs per scenario; each RunResult records its repeat (0-based)
    runs: list[RunResult]
    summary: Summary
