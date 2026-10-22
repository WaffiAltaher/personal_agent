# src/agent/evals/__main__.py
"""Run the eval suite against the Fixture world with a chosen model.

    uv run python -m agent.evals --model google_genai:gemini-3.8-flash
    uv run python -m agent.evals --model anthropic:claude-sonnet-5-5 --scenario finance-trial-balance
    uv run python -m agent.evals --model google_genai:gemini-3.8-flash --judge-model anthropic:claude-sonnet-5-5

Writes `<eval-run-id>.json` (raw results) and `<eval-run-id>.md` (report) to --out.
Needs the API keys of the model's and the judge model's providers, plus GOOGLE_API_KEY for the
embeddings answer relevancy uses; nothing else is real (no MS365 or Informer credentials, no
Gmail or Calendar). Each scenario run is a Langfuse trace, tagged with the model, prompt
version, scenario and eval-run id.

The judge model grades the answers (RAGAS). It is --judge-model, else EVAL_JUDGE_MODEL, else
the model under test itself: the command then says so, as the model grades its own answers.
--no-ragas skips the generation metrics (and the judge). --repeats N runs every scenario N
times, so the results show the run-to-run variation.

Compare two models from their results files (writes `compare-<run A>-vs-<run B>.md` to --out):

    uv run python -m agent.evals compare data/evals/<run A>.json data/evals/<run B>.json
"""

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from agent.chat_model import ModelConfigError, create_chat_model
from agent.config import settings
from agent.evals.compare import ResultsError, write_comparison
from agent.evals.generation import RagasScorer
from agent.evals.harness import run_eval, write_results
from agent.evals.scenarios import DEFAULT_DATASET, ScenarioError, load_dataset
from agent.tracing import flush_traces, langfuse_trace

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "data" / "evals"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m agent.evals", description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default=settings.model_name,
                        help="model under test, as provider:model (default: MODEL_NAME from settings)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="scenario dataset JSON file")
    parser.add_argument("--scenario", default=None, help="only run scenarios whose id contains this text")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for the results JSON and report")
    parser.add_argument("--judge-model", default=settings.eval_judge_model,
                        help="model grading the answers (RAGAS), as provider:model "
                             "(default: EVAL_JUDGE_MODEL from settings, else the model under test)")
    parser.add_argument("--no-ragas", action="store_true", help="skip the generation metrics and the judge")
    parser.add_argument("--repeats", type=_positive_int, default=1,
                        help="runs per scenario, to measure run-to-run variation (default: 1)")
    return parser.parse_args(argv)


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")
    return value


def _compare(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m agent.evals compare",
                                     description="Compare two models from their eval results files.")
    parser.add_argument("a", type=Path, help="results JSON of model A")
    parser.add_argument("b", type=Path, help="results JSON of model B")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for the comparison report")
    args = parser.parse_args(argv)
    path = write_comparison(args.a, args.b, args.out)
    print(f"Comparison: {path}")


def create_embeddings() -> Embeddings:
    """The embeddings RAGAS answer relevancy compares questions with (as semantic memory uses)."""
    return GoogleGenerativeAIEmbeddings(model=settings.chroma_embedding_model, google_api_key=settings.google_api_key)


async def main(
    argv: list[str],
    *,
    create_model: Callable[[str], BaseChatModel] = create_chat_model,
    create_embeddings: Callable[[], Embeddings] = create_embeddings,
) -> None:
    if argv[:1] == ["compare"]:
        return _compare(argv[1:])
    args = _parse_args(argv)
    dataset = load_dataset(args.dataset)
    model = create_model(args.model)  # fails fast on a missing API key, before any run

    scorer, judge_model = None, None
    if not args.no_ragas:
        judge_model = args.judge_model or args.model
        if judge_model == args.model:
            print(f"Warning: no judge model set (--judge-model or EVAL_JUDGE_MODEL), so {judge_model} "
                  "grades its own answers.")
        scorer = RagasScorer(judge=create_model(judge_model), embeddings=create_embeddings())

    try:
        results = await run_eval(
            dataset,
            model_name=args.model,
            model_factory=lambda scenario: model,
            scenario_filter=args.scenario,
            dataset_path=args.dataset,
            scorer=scorer,
            judge_model=judge_model,
            tracer=langfuse_trace,
            repeats=args.repeats,
        )
    finally:
        flush_traces()
    json_path, report_path = write_results(results, args.out)

    s = results.summary
    print(f"{results.model}: {s.passed}/{s.runs} passed (recall {s.mean_recall:.2f}, precision {s.mean_precision:.2f})")
    print(f"Results: {json_path}")
    print(f"Report:  {report_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except (ModelConfigError, ScenarioError, ResultsError) as exc:
        print(f"Cannot run evals: {exc}")
        sys.exit(1)
