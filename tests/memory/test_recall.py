"""
tests/memory/test_recall.py

Memory query rewriting: a model call turns the user's natural-language request
into a semantic query (Chroma) and keyword variants (SQLite episodic search).

The rewriter is a scripted fake chat model, the stores are temporary, and
embeddings are a fake that only knows a few topics — no network, no credentials.
"""

import itertools
import json
from unittest.mock import patch

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent.memory.episodic import EpisodicMemory, RunRecord
from agent.config import settings
from agent.memory.recall import create_rewrite_model, recall_chunks, recall_runs
from agent.memory.semantic import SemanticMemory


REQUEST = "what did I ask about invoices last week"


def rewriter_reply(semantic_query: str, keywords: list[str]) -> AIMessage:
    return AIMessage(content=json.dumps({"semantic_query": semantic_query, "keywords": keywords}))


class FailingModel(GenericFakeChatModel):
    """A rewriter whose provider call fails, e.g. the API is down."""

    def _generate(self, *args, **kwargs):
        raise ConnectionError("rewriter unavailable")


class TopicEmbeddings:
    """
    Toy embeddings: one dimension per known topic, set when any of its words
    appears in the text, plus a dimension every text shares (so relevance
    scores stay within 0..1). Texts sharing a topic score 1.0; texts with
    different topics score ~0.29, below the relevance threshold.
    """

    TOPICS = [
        {"invoice", "invoices", "informer", "overdue"},
        {"weather", "sunny", "rain"},
    ]

    def _embed(self, text: str) -> list[float]:
        words = set(text.lower().replace("?", " ").replace(".", " ").split())
        vec = [1.0 if words & topic else 0.0 for topic in self.TOPICS]
        vec += [0.0 if any(vec) else 1.0, 1.0]  # "no known topic", shared
        norm = sum(x * x for x in vec) ** 0.5
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@pytest.fixture
def semantic(tmp_path):
    with patch("agent.memory.semantic.GoogleGenerativeAIEmbeddings", return_value=TopicEmbeddings()):
        yield SemanticMemory(persist_dir=str(tmp_path / "chroma"))


@pytest.fixture
def episodic(tmp_path):
    db = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))
    yield db
    db.close()


def _run(user_input: str, final_output: str = "Done.") -> RunRecord:
    return RunRecord(user_input=user_input, final_output=final_output)


def test_paraphrase_finds_a_run_the_literal_query_misses(episodic, scripted_model):
    episodic.log_run(_run("Which Informer invoices are overdue?", "Three invoices are overdue."))
    episodic.log_run(_run("What is the weather today?", "Sunny."))
    rewriter = scripted_model([rewriter_reply("overdue Informer invoices", ["Informer", "overdue"])])

    assert episodic.search_runs(REQUEST) == []  # the literal query finds nothing
    runs = recall_runs(REQUEST, episodic, n=5, model=rewriter)

    assert [r.user_input for r in runs] == ["Which Informer invoices are overdue?"]


@pytest.mark.parametrize(
    "rewriter",
    [FailingModel(messages=iter([])), "unparseable"],
    ids=["model-error", "unparseable-reply"],
)
def test_rewriter_failure_falls_back_to_the_literal_query(episodic, scripted_model, rewriter):
    if rewriter == "unparseable":
        rewriter = scripted_model([AIMessage(content="Sure! Here are some keywords: invoices")])
    episodic.log_run(_run("show unpaid invoices", "Two unpaid invoices."))
    episodic.log_run(_run("What is the weather today?", "Sunny."))

    runs = recall_runs("unpaid invoices", episodic, n=5, model=rewriter)

    assert [r.user_input for r in runs] == ["show unpaid invoices"]


def test_runs_matching_more_variants_rank_first_without_duplicates(episodic, scripted_model):
    episodic.log_run(_run("Which Informer invoices are overdue?"))
    episodic.log_run(_run("List my Informer relations"))  # newer, but matches one variant only
    rewriter = scripted_model([rewriter_reply("overdue Informer invoices", ["Informer", "overdue"])])

    runs = recall_runs(REQUEST, episodic, n=5, model=rewriter)

    assert [r.user_input for r in runs] == [
        "Which Informer invoices are overdue?",
        "List my Informer relations",
    ]


def test_semantic_query_finds_an_interaction_the_literal_request_misses(semantic, scripted_model):
    memory_overdue = semantic.remember("Which Informer invoices are overdue? Three invoices are overdue.")
    semantic.remember("What is the weather today? Sunny.")
    request = "what did I ask about clients who still owe me money"
    rewriter = scripted_model([rewriter_reply("overdue Informer invoices", ["Informer", "overdue"])])

    assert semantic.search_all(request) == []  # the literal request finds nothing
    chunks = recall_chunks(request, semantic, k=5, model=rewriter)

    assert [c.metadata["memory_id"] for c in chunks] == [memory_overdue]


def test_rewrite_model_defaults_to_the_agent_model():
    agent_on_claude = settings.model_copy(update={
        "model_name": "anthropic:claude-sonnet-5-5", "anthropic_api_key": "sk-ant-dummy",
    })

    model = create_rewrite_model(agent_on_claude)

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-sonnet-5-5"


def test_rewrite_model_can_be_set_separately():
    cheaper_rewriter = settings.model_copy(update={
        "model_name": "google_genai:gemini-3.8-flash",
        "memory_rewrite_model": "anthropic:claude-haiku-5-5",
        "anthropic_api_key": "sk-ant-dummy",
    })

    model = create_rewrite_model(cheaper_rewriter)

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-haiku-5-5"


def test_rewrite_model_that_cannot_be_built_falls_back_to_the_literal_query(episodic, monkeypatch):
    monkeypatch.setattr(settings, "memory_rewrite_model", "anthropic:claude-haiku-5-5")
    monkeypatch.setattr(settings, "anthropic_api_key", None)  # MissingApiKeyError when building it
    episodic.log_run(_run("show unpaid invoices"))

    runs = recall_runs("unpaid invoices", episodic, n=5)  # no injected model: built from settings

    assert [r.user_input for r in runs] == ["show unpaid invoices"]


# ---------------------------------------------------------------------------
# The memory retrieval tools: both rewrite the user's request before searching.
# The shared memory singletons and the rewriting model are swapped for the
# temporary stores and a scripted rewriter.
# ---------------------------------------------------------------------------

@pytest.fixture
def tool_memory(monkeypatch, episodic, semantic, scripted_model):
    import agent.memory
    import agent.memory.recall

    monkeypatch.setattr(agent.memory, "_episodic", episodic)
    monkeypatch.setattr(agent.memory, "_semantic", semantic)
    rewriter = scripted_model([rewriter_reply("overdue Informer invoices", ["Informer", "overdue"])])
    monkeypatch.setattr(agent.memory.recall, "create_rewrite_model", lambda: rewriter)
    agent.memory.recall.clear_rewrite_cache()
    return episodic, semantic


@pytest.fixture
def counted_rewriter(monkeypatch, tool_memory, scripted_model):
    """A rewriter that answers every call, counting the models built and the calls made."""
    import agent.memory.recall

    counts = {"built": 0, "calls": []}

    def reply(messages):
        counts["calls"].append(messages[-1].content)
        return rewriter_reply("overdue Informer invoices", ["Informer", "overdue"])

    def build():
        counts["built"] += 1
        return scripted_model(itertools.repeat(reply))

    monkeypatch.setattr(agent.memory.recall, "create_rewrite_model", build)
    return counts


def test_both_memory_tools_share_one_rewrite_of_the_same_request(counted_rewriter):
    from agent.tools.memory import retrieve_episodic_memory, retrieve_memory

    retrieve_episodic_memory.invoke({"query": REQUEST})
    retrieve_memory.invoke({"query": REQUEST})

    assert counted_rewriter["calls"] == [REQUEST]


def test_the_rewrite_model_is_built_once_for_many_requests(counted_rewriter):
    from agent.tools.memory import retrieve_memory

    retrieve_memory.invoke({"query": REQUEST})
    retrieve_memory.invoke({"query": "unpaid invoices"})

    assert counted_rewriter["built"] == 1
    assert counted_rewriter["calls"] == [REQUEST, "unpaid invoices"]


def test_retrieve_episodic_memory_tool_rewrites_the_request(tool_memory):
    from agent.tools.memory import retrieve_episodic_memory

    episodic, _ = tool_memory
    episodic.log_run(_run("Which Informer invoices are overdue?", "Three invoices are overdue."))

    result = retrieve_episodic_memory.invoke({"query": REQUEST})

    assert "Which Informer invoices are overdue?" in result


def test_retrieve_memory_tool_rewrites_the_request(tool_memory):
    from agent.tools.memory import retrieve_memory

    _, semantic = tool_memory
    semantic.remember("Which Informer invoices are overdue? Three invoices are overdue.")

    result = retrieve_memory.invoke({"query": "what did I ask about clients who still owe me money"})

    assert "Which Informer invoices are overdue?" in result
