# src/agent/evals/__main__.py
"""Run the eval suite against the Fixture world with a chosen model.

    uv run python -m agent.evals --model google_genai:gemini-3.8-flash
    uv run python -m agent.evals --model anthropic:claude-sonnet-5-5 --scenario overdue

Writes `<eval-run-id>.json` (raw results) and `<eval-run-id>.md` (report) to --out.
Needs the API key of the model's provider; nothing else is real (no MS365 or Informer
credentials, no Gmail or Calendar).
"""

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from agent.chat_model import MissingApiKeyError, create_chat_model
from agent.config import settings
from agent.evals.harness import run_eval, write_results
from agent.evals.scenarios import DEFAULT_DATASET, ScenarioError, load_dataset

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "data" / "evals"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m agent.evals", description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default=settings.model_name,
                        help="model under test, as provider:model (default: MODEL_NAME from settings)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="scenario dataset JSON file")
    parser.add_argument("--scenario", default=None, help="only run scenarios whose id contains this text")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for the results JSON and report")
    return parser.parse_args(argv)


async def main(argv: list[str], *, create_model: Callable[[str], BaseChatModel] = create_chat_model) -> None:
    args = _parse_args(argv)
    dataset = load_dataset(args.dataset)
    model = create_model(args.model)  # fails fast on a missing API key, before any run

    results = await run_eval(
        dataset,
        model_name=args.model,
        model_factory=lambda scenario: model,
        scenario_filter=args.scenario,
        dataset_path=args.dataset,
    )
    json_path, report_path = write_results(results, args.out)

    s = results.summary
    print(f"{results.model}: {s.passed}/{s.runs} passed (recall {s.mean_recall:.2f}, precision {s.mean_precision:.2f})")
    print(f"Results: {json_path}")
    print(f"Report:  {report_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except (MissingApiKeyError, ScenarioError) as exc:
        print(f"Cannot run evals: {exc}")
        sys.exit(1)
