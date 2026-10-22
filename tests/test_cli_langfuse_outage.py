"""
tests/test_cli_langfuse_outage.py

When Langfuse can't be reached (refused connection, bad keys, any error from its auth check),
`python -m agent.cli` prints a warning naming the configured Langfuse base URL and runs the
agent untraced. Driven through the CLI's main(); only the Langfuse auth call (a system boundary)
is replaced, the rest of the real startup path runs.
"""

import sys
from contextlib import asynccontextmanager

import httpx
import pytest
from langchain_core.messages import AIMessage
from langfuse import Langfuse
from langgraph.checkpoint.memory import InMemorySaver

import agent.cli as cli


OUTAGE_BASE_URL = "http://langfuse.lan.test:4318"  # not the default, so a hard-coded URL would fail


def _connection_refused(*args, **kwargs):
    raise httpx.ConnectError("[Errno 61] Connection refused")


def _http_error(*args, **kwargs):
    request = httpx.Request("GET", f"{OUTAGE_BASE_URL}/api/public/projects")
    response = httpx.Response(401, request=request)
    raise httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)


def _no_project(*args, **kwargs):
    raise RuntimeError("Auth check failed, no project found for the keys provided.")


@pytest.fixture
def run_cli_against_langfuse(monkeypatch, scripted_model, langfuse_spans):
    """Run the CLI's main() with the real Langfuse wiring; returns (run, what the run saw)."""
    seen = {"logged_to_memory": []}

    def reply(messages):
        return AIMessage(content="Your calendar is empty on Monday.")

    async def load_all_tools(*, fixtures=False):
        return [], []

    @asynccontextmanager
    async def get_checkpointer():
        yield InMemorySaver()

    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([reply]))
    monkeypatch.setattr(cli, "check_google_login", lambda: None)
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(
        cli,
        "log_run_to_memory",
        lambda result, user_input, **kwargs: seen["logged_to_memory"].append(user_input),
    )
    monkeypatch.setattr(cli.settings, "langfuse_base_url", OUTAGE_BASE_URL)

    def set_auth_check(auth_check):
        monkeypatch.setattr(Langfuse, "auth_check", auth_check)

    async def run(*args):
        monkeypatch.setattr(sys, "argv", ["agent.cli", *args])
        await cli.main()
        return seen

    return run, set_auth_check, langfuse_spans


@pytest.mark.asyncio
async def test_run_completes_and_warns_with_the_base_url_when_langfuse_refuses_connection(
        run_cli_against_langfuse, capsys):
    run, set_auth_check, _ = run_cli_against_langfuse
    set_auth_check(_connection_refused)

    seen = await run("Is my calendar empty on Monday?")

    out = capsys.readouterr().out
    assert "Your calendar is empty on Monday." in out
    assert "Langfuse" in out and OUTAGE_BASE_URL in out
    assert seen["logged_to_memory"] == ["Is my calendar empty on Monday?"]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_check_error", [_http_error, _no_project], ids=["http-error", "no-project"])
async def test_any_other_auth_check_failure_is_treated_the_same_way(
        run_cli_against_langfuse, capsys, auth_check_error):
    run, set_auth_check, _ = run_cli_against_langfuse
    set_auth_check(auth_check_error)

    seen = await run("Is my calendar empty on Monday?")

    out = capsys.readouterr().out
    assert "Your calendar is empty on Monday." in out
    assert "Langfuse" in out and OUTAGE_BASE_URL in out
    assert seen["logged_to_memory"] == ["Is my calendar empty on Monday?"]


@pytest.mark.asyncio
async def test_a_run_with_langfuse_down_records_no_traces(run_cli_against_langfuse):
    run, set_auth_check, langfuse_spans = run_cli_against_langfuse
    set_auth_check(_connection_refused)

    await run("Is my calendar empty on Monday?")

    assert len(langfuse_spans()) == 0


@pytest.mark.asyncio
async def test_a_run_with_langfuse_up_records_traces_and_prints_no_warning(
        run_cli_against_langfuse, capsys):
    run, set_auth_check, langfuse_spans = run_cli_against_langfuse
    set_auth_check(lambda self: True)

    await run("Is my calendar empty on Monday?")

    assert "Warning" not in capsys.readouterr().out
    assert len(langfuse_spans()) > 0
