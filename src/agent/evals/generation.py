# src/agent/evals/generation.py
"""Generation metrics: RAGAS scores of a run's final answer, graded by a judge model.

RAGAS (ADR-007, generation level) scores the answer with its 0.4 "collections" metrics:
- faithfulness: are the answer's claims supported by the contexts?
- answer relevancy: does the answer address the question? (judge + embeddings)
- context precision: are the useful contexts ranked first? (against the reference)
- context recall: is the reference covered by the contexts?

The contexts are the outputs of the run's successful tool calls, in call order; the reference
is the scenario's expected facts, one per line. A metric without what it needs is not scored
and says why in `GenerationScores.notes`, as does a judge failure: scoring never stops an eval.

The judge is any LangChain chat model (agent.chat_model.create_chat_model), adapted to RAGAS's
LLM interface by ChatModelJudge: RAGAS's prompts already carry the JSON schema of the answer
they want, so the judge's reply text is parsed as that JSON. Answer relevancy also needs
embeddings, adapted from any LangChain Embeddings.
"""

import math
import os
from dataclasses import dataclass
from statistics import mean
from typing import Protocol, TypeVar

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from agent.evals.records import GenerationScores, RunResult
from agent.evals.scenarios import Scenario

# RAGAS sends usage telemetry unless this is set; eval runs send nothing to third parties.
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

from ragas.embeddings.base import BaseRagasEmbedding  # noqa: E402
from ragas.llms.base import InstructorBaseRagasLLM  # noqa: E402
from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness  # noqa: E402

T = TypeVar("T", bound=BaseModel)

METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


class JudgeReplyError(ValueError):
    """The judge's reply is not the JSON the RAGAS prompt asked for."""


def _parse(reply: AIMessage, response_model: type[T]) -> T:
    text = reply.text
    start, end = text.find("{"), text.rfind("}")  # tolerate ```json fences and preambles
    try:
        return response_model.model_validate_json(text[start:end + 1] if start != -1 else text)
    except ValidationError as exc:
        raise JudgeReplyError(
            f"judge reply is not valid JSON for {response_model.__name__}: {text[:200]!r}") from exc


class ChatModelJudge(InstructorBaseRagasLLM):
    """A LangChain chat model as a RAGAS judge LLM."""

    def __init__(self, model: BaseChatModel):
        self.model = model

    def generate(self, prompt: str, response_model: type[T]) -> T:
        return _parse(self.model.invoke([HumanMessage(content=prompt)]), response_model)

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        return _parse(await self.model.ainvoke([HumanMessage(content=prompt)]), response_model)


class LangChainEmbeddings(BaseRagasEmbedding):
    """LangChain Embeddings as RAGAS embeddings."""

    def __init__(self, embeddings: Embeddings):
        super().__init__()
        self.embeddings = embeddings

    def embed_text(self, text: str, **kwargs) -> list[float]:
        return self.embeddings.embed_query(text)

    async def aembed_text(self, text: str, **kwargs) -> list[float]:
        return await self.embeddings.aembed_query(text)


@dataclass(frozen=True)
class GenerationSample:
    """What the generation metrics score for one run."""
    user_input: str
    response: str
    contexts: list[str]
    reference: str


def generation_sample(scenario: Scenario, run: RunResult) -> GenerationSample:
    return GenerationSample(
        user_input=scenario.input,
        response=run.final_answer,
        contexts=[c.output for c in run.tool_calls if c.status == "success" and c.output],
        reference="\n".join(scenario.expected_facts),
    )


class GenerationScorer(Protocol):
    async def score(self, sample: GenerationSample) -> GenerationScores: ...


class RagasScorer:
    """Scores samples with the four RAGAS metrics, graded by `judge`."""

    def __init__(self, *, judge: BaseChatModel, embeddings: Embeddings):
        llm = ChatModelJudge(judge)
        self._metrics = {
            "faithfulness": Faithfulness(llm=llm),
            "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=LangChainEmbeddings(embeddings)),
            "context_precision": ContextPrecision(llm=llm),
            "context_recall": ContextRecall(llm=llm),
        }

    async def score(self, sample: GenerationSample) -> GenerationScores:
        q, a, ctx, ref = sample.user_input, sample.response, sample.contexts, sample.reference
        inputs = {
            "faithfulness": dict(user_input=q, response=a, retrieved_contexts=ctx),
            "answer_relevancy": dict(user_input=q, response=a),
            "context_precision": dict(user_input=q, reference=ref, retrieved_contexts=ctx),
            "context_recall": dict(user_input=q, retrieved_contexts=ctx, reference=ref),
        }
        scores: dict[str, float | None] = {}
        notes: dict[str, str] = {}
        for name, kwargs in inputs.items():
            missing = _missing(kwargs)
            if missing:
                scores[name], notes[name] = None, missing
                continue
            try:
                value = (await self._metrics[name].ascore(**kwargs)).value
            except Exception as exc:  # a judge failure is recorded, not raised
                scores[name], notes[name] = None, f"{type(exc).__name__}: {exc}"
                continue
            if value is None or math.isnan(value):
                scores[name], notes[name] = None, "the judge found nothing to score"
            else:
                scores[name] = float(value)
        return GenerationScores(**scores, contexts=len(ctx), notes=notes)


def _missing(kwargs: dict) -> str | None:
    if "response" in kwargs and not kwargs["response"]:
        return "no final answer"
    if "retrieved_contexts" in kwargs and not kwargs["retrieved_contexts"]:
        return "no successful tool output to use as contexts"
    if "reference" in kwargs and not kwargs["reference"]:
        return "the scenario has no expected facts to use as reference"
    return None


def generation_means(runs: list[RunResult]) -> dict:
    """Summary fields: each metric's mean over the runs that have a score for it."""
    means = {}
    for name in METRICS:
        values = [getattr(r.generation, name) for r in runs if r.generation is not None]
        values = [v for v in values if v is not None]
        means[f"mean_{name}"] = mean(values) if values else None
    return means
