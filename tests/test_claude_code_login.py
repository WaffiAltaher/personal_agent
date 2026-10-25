"""
Claude Code login at startup (real CLI mode), for a `claude_code:` agent or judge model.

Seam: the CLI driver. The real CLI is never called: CLAUDE_CODE_BINARY points at the Fixture
world's stand-in, which records the call and prints a scripted `claude auth status` JSON.
"""

import contextlib
import json
import os
import signal
import sys
from contextlib import asynccontextmanager

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import agent.auth.claude_code as claude_code_auth
import agent.cli as cli
from agent.config import settings
from fixture_world import claude_code as fake_cli

LOGGED_IN = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "pro"}


@pytest.fixture
def run_cli(monkeypatch, scripted_model, tmp_path):
    """Real-mode CLI with a `claude_code:` agent model; status(json) scripts `claude auth status`."""
    calls_path, replies_path = tmp_path / "calls.jsonl", tmp_path / "replies.json"
    monkeypatch.setenv(fake_cli.CALLS_ENV, str(calls_path))
    monkeypatch.setenv(fake_cli.REPLIES_ENV, str(replies_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-exported")
    monkeypatch.setattr(settings, "model_name", "claude_code:sonnet")
    monkeypatch.setattr(settings, "eval_judge_model", None)
    monkeypatch.setattr(settings, "claude_code_binary", fake_cli.binary())

    async def load_all_tools(*, fixtures=False):
        return [], []

    @asynccontextmanager
    async def get_checkpointer():
        yield InMemorySaver()

    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([lambda _m: AIMessage(content="ok")]))
    monkeypatch.setattr(cli, "verify_connection", lambda: True)
    monkeypatch.setattr(cli, "get_callback_handler", lambda **kwargs: BaseCallbackHandler())
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(cli, "log_run_to_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "flush_traces", lambda: None)
    monkeypatch.setattr(cli, "check_google_login", lambda: None)

    class Run:
        @staticmethod
        def status(reply):
            replies_path.write_text(json.dumps([reply]))

        @staticmethod
        def calls():
            return fake_cli.recorded_calls(calls_path)

        @staticmethod
        async def start(*args):
            monkeypatch.setattr(sys, "argv", ["agent.cli", *args])
            await cli.main()

    return Run


@pytest.mark.asyncio
async def test_claude_ai_login_lets_the_run_start_after_one_status_call_without_api_keys(run_cli, capsys):
    run_cli.status(LOGGED_IN)

    await run_cli.start("What is in my inbox?")

    [call] = run_cli.calls()
    assert call["args"] == ["auth", "status"]
    assert "ANTHROPIC_API_KEY" not in call["env"]
    assert "ok" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"},
    {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"},
], ids=["logged-out", "api-key-login"])
async def test_no_claude_ai_login_stops_startup_naming_claude_auth_login(run_cli, capsys, status):
    run_cli.status(status)

    with pytest.raises(SystemExit) as exc:
        await run_cli.start("What is in my inbox?")

    assert exc.value.code == 1
    assert "claude auth login" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_missing_binary_stops_startup_with_not_found_on_path(run_cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(settings, "claude_code_binary", str(tmp_path / "no-such-claude"))

    with pytest.raises(SystemExit) as exc:
        await run_cli.start("What is in my inbox?")

    assert exc.value.code == 1
    assert "Claude Code not found on PATH" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_a_hung_status_call_stops_startup_with_a_message_not_a_traceback(run_cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(claude_code_auth, "LOGIN_CHECK_TIMEOUT_S", 1)
    run_cli.status({"hang": True})

    try:
        with pytest.raises(SystemExit) as exc:
            await run_cli.start("What is in my inbox?")
    finally:
        for pid in fake_cli.hung_pids(tmp_path / "calls.jsonl"):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)

    assert exc.value.code == 1
    out, err = capsys.readouterr()
    assert "Claude Code did not answer `claude auth status` within 1 s" in out
    assert "Traceback" not in out + err


@pytest.mark.asyncio
async def test_claude_code_judge_model_alone_also_triggers_the_check(run_cli, monkeypatch, capsys):
    monkeypatch.setattr(settings, "model_name", "google_genai:gemini-3.8-flash")
    monkeypatch.setattr(settings, "eval_judge_model", "claude_code:haiku")
    run_cli.status({"loggedIn": False})

    with pytest.raises(SystemExit):
        await run_cli.start("What is in my inbox?")

    assert "claude auth login" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("model, args", [
    ("claude_code:sonnet", ["--fixtures", "What is in my inbox?"]),
    ("google_genai:gemini-3.8-flash", ["What is in my inbox?"]),
], ids=["fixtures-mode", "other-provider"])
async def test_check_is_skipped_in_fixtures_mode_or_without_a_claude_code_model(run_cli, monkeypatch, model, args):
    monkeypatch.setattr(settings, "model_name", model)
    run_cli.status({"loggedIn": False})

    await run_cli.start(*args)

    assert run_cli.calls() == []
