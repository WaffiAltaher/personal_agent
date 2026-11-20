"""
`python -m agent.web` startup: the web-only checks (password hash, built app), then the CLI's
startup steps through `agent.startup`, with the CLI's exact messages. The server itself is never
started: `serve(run=...)` gets a stand-in that records the app it was handed.
"""

import sys

import pytest
from langchain_core.messages import AIMessage

import agent.cli as cli
import agent.graph as graph
import agent.startup as startup
import agent.web.server as server
from agent.auth.claude_code import ClaudeCodeLoginRequired
from agent.auth.google import GoogleLoginRequired
from agent.config import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def web_start(monkeypatch, tmp_path, scripted_model, startup_login_checks_pass, capsys):
    """Run serve() as far as starting uvicorn; returns (start, what it saw)."""
    monkeypatch.setattr(graph, "CHECKPOINT_DB", str(tmp_path / "hitl.db"))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    monkeypatch.setattr(server, "WEB_DIST", dist)
    monkeypatch.setattr(settings, "web_password_hash", "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$aGFzaA")
    monkeypatch.setattr(server, "create_chat_model", lambda: scripted_model([]))
    monkeypatch.setattr(startup, "verify_connection", lambda: True)
    monkeypatch.setattr(server, "flush_traces", lambda: None)
    seen = {"notices": [], "apps": []}

    async def load_all_tools(*, fixtures=False):
        seen["fixtures"] = fixtures
        return [], list(seen["notices"])
    monkeypatch.setattr(server, "load_all_tools", load_all_tools)

    async def run(app, web):
        seen["apps"].append((app, web))

    async def start():
        await server.serve(run=run)
        return capsys.readouterr().out
    return start, seen


async def cli_output(monkeypatch, scripted_model, capsys, notices=()):
    """What a real-mode CLI startup prints, with the same stand-ins (exits are caught)."""
    async def load_all_tools(*, fixtures=False):
        return [], list(notices)
    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([AIMessage(content="ok")]))
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "flush_traces", lambda: None)
    monkeypatch.setattr(sys, "argv", ["agent.cli"])
    capsys.readouterr()
    try:
        await cli.main()
    except SystemExit:
        pass
    return capsys.readouterr().out


async def test_starts_the_app_on_the_configured_host_and_port_against_real_data(web_start, monkeypatch):
    start, seen = web_start
    monkeypatch.setattr(settings, "web_port", 8123)

    await start()

    (app, web), = seen["apps"]
    assert (web.host, web.port) == ("127.0.0.1", 8123)
    assert seen["fixtures"] is False
    assert app.state.checkpoint_path == graph.CHECKPOINT_DB


async def test_without_a_password_hash_startup_stops_naming_set_password(web_start, monkeypatch):
    start, seen = web_start
    monkeypatch.setattr(settings, "web_password_hash", None)

    with pytest.raises(SystemExit) as exited:
        await start()

    assert exited.value.code == 1
    assert seen["apps"] == []


async def test_messages_name_the_fix(web_start, monkeypatch, capsys, tmp_path):
    start, _ = web_start
    monkeypatch.setattr(settings, "web_password_hash", None)
    with pytest.raises(SystemExit):
        await start()
    assert "python -m agent.web.set_password" in capsys.readouterr().out

    monkeypatch.setattr(settings, "web_password_hash", "$argon2id$x")
    monkeypatch.setattr(server, "WEB_DIST", tmp_path / "not-built")
    with pytest.raises(SystemExit) as exited:
        await start()
    assert exited.value.code == 1
    assert "npm run build" in capsys.readouterr().out


@pytest.mark.parametrize("failing", ["google", "claude_code"])
async def test_a_dead_login_stops_startup_with_the_clis_message(web_start, monkeypatch, scripted_model, capsys, failing):
    start, seen = web_start
    monkeypatch.setattr(settings, "model_name", "claude_code:claude-sonnet-5-5")
    if failing == "google":
        def check():
            raise GoogleLoginRequired("Google login expired. Run: python -m agent.auth.google")
        monkeypatch.setattr(startup, "check_google_login", check)
    else:
        def check(binary):
            raise ClaudeCodeLoginRequired("Claude Code is not logged in. Run: claude auth login")
        monkeypatch.setattr(startup, "check_claude_code_login", check)

    with pytest.raises(SystemExit) as exited:
        await start()
    web_out = capsys.readouterr().out
    cli_out = await cli_output(monkeypatch, scripted_model, capsys)

    assert exited.value.code == 1
    assert seen["apps"] == []
    stop = [line for line in web_out.splitlines() if line.startswith("Cannot start:")]
    assert stop and stop == [line for line in cli_out.splitlines() if line.startswith("Cannot start:")]


async def test_skipped_mcp_servers_print_the_clis_notices(web_start, monkeypatch, scripted_model, capsys):
    start, seen = web_start
    seen["notices"] = ["MS365 tools unavailable: not logged in. Run: npx @softeria/ms-365-mcp-server --login"]

    web_out = await start()
    cli_out = await cli_output(monkeypatch, scripted_model, capsys, notices=seen["notices"])

    notice = [line for line in web_out.splitlines() if line.startswith("Notice:")]
    assert notice == [f"Notice: {seen['notices'][0]}"]
    assert notice == [line for line in cli_out.splitlines() if line.startswith("Notice:")]
    assert len(seen["apps"]) == 1


async def test_langfuse_down_warns_as_the_cli_does_and_still_starts(web_start, monkeypatch, scripted_model, capsys):
    start, seen = web_start
    monkeypatch.setattr(startup, "verify_connection", lambda: False)

    web_out = await start()
    cli_out = await cli_output(monkeypatch, scripted_model, capsys)

    warning = [line for line in web_out.splitlines() if line.startswith("Warning:")]
    assert warning and warning == [line for line in cli_out.splitlines() if line.startswith("Warning:")]
    (app, _), = seen["apps"]
    assert app.state.langfuse_connected is False


@pytest.mark.parametrize("model_name,names", [
    ("claude_code:claude-sonnet-5-5", ["Google", "Claude Code", "ms365", "informer"]),
    ("google_genai:gemini-3.8-flash", ["Google", "ms365", "informer"]),
])
async def test_the_login_status_strip_starts_from_what_startup_found(web_start, monkeypatch, model_name, names):
    start, seen = web_start
    monkeypatch.setattr(settings, "model_name", model_name)
    monkeypatch.setattr(settings, "eval_judge_model", None)
    seen["notices"] = ["ms365 tools unavailable: not logged in to Microsoft 365 (No valid token found)."]

    await start()

    (app, _), = seen["apps"]
    status = {row["name"]: row for row in app.state.logins.status()}
    assert list(status) == names
    assert status["Google"]["alive"] is True
    assert (status["ms365"]["alive"], status["ms365"]["detail"]) == (False, seen["notices"][0])
