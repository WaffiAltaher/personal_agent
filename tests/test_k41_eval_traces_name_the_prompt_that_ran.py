from pathlib import Path

from agent.evals import harness
from agent.evals.scenarios import load_dataset

DATASET = Path(__file__).parent / "fixtures" / "evals" / "scenarios.json"


def test_eval_traces_are_tagged_with_the_prompt_version_that_ran(monkeypatch):
    # Not the default (v3): a test that only uses the default can't tell "the configured
    # version" from "always v3".
    monkeypatch.setattr(harness.settings, "prompt_version", "v2")
    scenario = load_dataset(DATASET).scenarios[0]

    attributes = harness.trace_attributes(scenario, model_name="m", eval_run_id="r", repeat=0)

    assert "prompt:v2" in attributes.tags
    assert attributes.metadata["prompt_version"] == "v2"
