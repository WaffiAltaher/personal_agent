# src/agent/evals/scenarios.py
"""The versioned scenario format and its loader.

A dataset is one JSON file:

    {
      "format_version": 1,              # this file's schema; bumped on an incompatible change
      "dataset_version": "2026-10-07",  # the scenarios' own version, recorded in every result
      "scenarios": [
        {
          "id": "reply-flaky-mailbox",        # unique; what the --scenario filter matches
          "workflow": "failure recovery",
          "input": "Find Jan's mail about invoice 2026-031 and draft a reply.",
          "approval": "approve",              # every approval prompt is approved, or "reject"ed
          "inject_failure": {"server": "ms365", "mode": "transient", "times": 1},  # optional
          "required_tools": ["ms365_list-mail-messages", "ms365_create-reply-draft"],
          "ordering": [{"before": "ms365_list-mail-messages", "after": "ms365_create-reply-draft"}],
          "forbidden_tools": ["create_draft_email", "ms365_send-mail"],
          "expected_facts": ["Tuesday"]       # strings the final answer should contain
        }
      ]
    }

Tool names are the names bound to the graph (MCP tools carry their server prefix).
An injected failure is switched on once the tools are loaded, so it hits the run, not startup:
- ms365: a `fixture_world.ms365.Failure` mode; `times` limits it to the next N tool calls.
- informer: a `fixture_world.informer_api.Failure` mode, on every request (no `times`).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from fixture_world.informer_api import Failure as InformerFailure
from fixture_world.ms365 import Failure as Ms365Failure

FORMAT_VERSION = 1
DEFAULT_DATASET = Path(__file__).parent / "datasets" / "scenarios.json"


class ScenarioError(ValueError):
    """The dataset file is missing, malformed or of an unsupported format version."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FailureInjection(_Strict):
    server: Literal["ms365", "informer"]
    mode: str
    times: int | None = None

    @model_validator(mode="after")
    def _known_mode(self):
        modes = {m.value for m in (Ms365Failure if self.server == "ms365" else InformerFailure)}
        if self.mode not in modes:
            raise ValueError(f"unknown {self.server} failure mode {self.mode!r}; one of {sorted(modes)}")
        if self.server == "informer" and self.times is not None:
            raise ValueError("an informer failure applies to every request; it takes no 'times'")
        return self


class OrderingConstraint(_Strict):
    """`before` is first called before `after` is first called (both must be called)."""
    before: str
    after: str


class Scenario(_Strict):
    id: str
    workflow: str = ""
    input: str
    approval: Literal["approve", "reject"]
    inject_failure: FailureInjection | None = None
    required_tools: list[str] = []
    ordering: list[OrderingConstraint] = []
    forbidden_tools: list[str] = []
    expected_facts: list[str] = []


class Dataset(_Strict):
    format_version: int
    dataset_version: str
    scenarios: list[Scenario]

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [s.id for s in self.scenarios]
        if duplicates := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"duplicate scenario ids: {duplicates}")
        return self

    def select(self, pattern: str | None = None) -> list[Scenario]:
        """The scenarios whose id contains `pattern` (all of them without one)."""
        return [s for s in self.scenarios if not pattern or pattern in s.id]


def load_dataset(path: Path | str = DEFAULT_DATASET) -> Dataset:
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"cannot read scenario dataset {path}: {exc}") from exc
    version = raw.get("format_version") if isinstance(raw, dict) else None
    if version != FORMAT_VERSION:
        raise ScenarioError(f"{path}: unsupported format_version {version!r} (expected {FORMAT_VERSION})")
    try:
        return Dataset.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioError(f"{path}: invalid scenario dataset\n{exc}") from exc
