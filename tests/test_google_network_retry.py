"""
tests/test_google_network_retry.py

The Google SDK retries error replies (408/429/5xx) but not a request that timed out or lost its
connection. The agent retries those itself: the Gemini chat call through the graph's
with_network_retry, the embeddings through RetryingGoogleEmbeddings. A local server stands in
for the Gemini API and plays a script, one step per request: hang (never answer), an HTTP
status, or a real reply. No request leaves the machine.
"""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.chat_model import GOOGLE_NETWORK_ERRORS, create_chat_model, create_embeddings
from agent.config import settings
from agent.graph import build_graph
from agent.model_binding import bind_agent_tools, with_network_retry

GEMINI_REPLY = {
    "candidates": [{"content": {"role": "model", "parts": [{"text": "All good."}]}, "finishReason": "STOP", "index": 0}],
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5},
}
EMBED_REPLY = {"embedding": {"values": [0.1, 0.2, 0.3]}, "embeddings": [{"values": [0.1, 0.2, 0.3]}]}


@contextmanager
def scripted_gemini(monkeypatch, steps: list):
    """Serve the Gemini API locally; each request takes the next step: "hang", a status code,
    or a JSON reply body. Yields the list of request paths received."""
    script = list(steps)
    received: list[str] = []
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            received.append(self.path)
            step = script.pop(0) if script else 500
            if step == "hang":
                stop.wait()  # never answer while the test runs
                return
            body = json.dumps(step if isinstance(step, dict) else {"error": {"code": step, "status": "UNAVAILABLE",
                                                                             "message": "high demand"}}).encode()
            self.send_response(200 if isinstance(step, dict) else step)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        yield received
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


@pytest.fixture
def fast_timeout():
    return settings.model_copy(update={"model_timeout_s": 0.5, "google_api_key": "test-key"})


@tool
def lookup(query: str) -> str:
    """Look something up."""
    return "nothing"


@pytest.mark.asyncio
async def test_a_gemini_call_that_hangs_and_then_gets_a_503_is_retried_until_it_answers(monkeypatch, fast_timeout):
    with scripted_gemini(monkeypatch, ["hang", 503, GEMINI_REPLY]) as received:
        model = create_chat_model("google_genai:gemini-3.8-flash", settings=fast_timeout)
        graph = build_graph(checkpointer=InMemorySaver(), tools=[lookup], model=model)

        result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]},
                                     {"configurable": {"thread_id": "retry"}})

    assert result["messages"][-1].content == "All good."
    assert len(received) == 3  # the hang retried by the agent, the 503 by the Google SDK


@pytest.mark.asyncio
async def test_a_gemini_call_that_keeps_hanging_fails_after_the_allowed_attempts(monkeypatch, fast_timeout):
    with scripted_gemini(monkeypatch, ["hang"] * 5) as received:
        model = create_chat_model("google_genai:gemini-3.8-flash", settings=fast_timeout)
        call = with_network_retry(bind_agent_tools(model, [lookup]), model)

        with pytest.raises(GOOGLE_NETWORK_ERRORS):
            await call.ainvoke("hi")

    assert len(received) == 2  # MODEL_ATTEMPTS


def test_anthropic_models_are_left_to_their_sdks_own_retries():
    model = ChatAnthropic(model="claude-sonnet-5-5", api_key="sk-ant-test")
    bound = bind_agent_tools(model, [lookup])

    assert with_network_retry(bound, model) is bound


def test_an_embeddings_request_that_hangs_and_then_gets_a_503_is_retried_until_it_answers(monkeypatch, fast_timeout):
    with scripted_gemini(monkeypatch, ["hang", 503, EMBED_REPLY]) as received:
        embeddings = create_embeddings(settings=fast_timeout)

        assert embeddings.embed_query("hello") == [0.1, 0.2, 0.3]

    assert len(received) == 3


@pytest.mark.asyncio
async def test_an_async_embeddings_request_that_hangs_is_retried(monkeypatch, fast_timeout):
    with scripted_gemini(monkeypatch, ["hang", EMBED_REPLY]) as received:
        embeddings = create_embeddings(settings=fast_timeout)

        assert await embeddings.aembed_documents(["hello"]) == [[0.1, 0.2, 0.3]]

    assert len(received) == 2
