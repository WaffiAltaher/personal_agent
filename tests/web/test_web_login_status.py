"""
The login status strip, rechecked at the start of every turn (ticket web-interface/06).

Seam: the served app (GET /api/logins and the Conversation's event stream), with the real checks
built by ``agent.web.logins`` against Fixture-world stand-ins: a temp Google token, the stand-in
Claude Code CLI, the stand-in MS365 server switched logged out and back in. No live logins.
"""

import asyncio
import datetime
import json
import sys
import time

import pytest
from google.oauth2.credentials import Credentials

import agent.auth.google as google_auth
from agent.auth.claude_code import CLAUDE_CODE_LOGIN_COMMAND
from agent.auth.google import GOOGLE_LOGIN_COMMAND, SCOPES
from agent.tools.mcp_loader import LoginCheck, McpServer, load_mcp_tools
from agent.tools.ms365_mcp import LOGIN, ms365_fixture_server
from agent.web.logins import Integration, Logins, claude_code_login, google_login, startup_logins
from fixture_world import claude_code as fake_cli
from fixture_world.ms365 import FAILURE_FILE_ENV, Failure, FailureSwitch
from web.test_web_turns import TOOLS, ai, serve  # noqa: F401

pytestmark = pytest.mark.asyncio


def _write_token(path, *, expires_in: datetime.timedelta):
    creds = Credentials(token="access", refresh_token="refresh", token_uri="https://oauth2.googleapis.com/token",
                        client_id="test-client-id", client_secret="test-secret", scopes=SCOPES)
    creds.expiry = (datetime.datetime.now(datetime.timezone.utc) + expires_in).replace(tzinfo=None)
    path.write_text(creds.to_json())


@pytest.fixture
def google_token(monkeypatch, tmp_path):
    """The Google token file, fresh; the test deletes or rewrites it."""
    secrets = tmp_path / "google_credentials.json"
    secrets.write_text(json.dumps({"installed": {
        "client_id": "test-client-id", "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
    }}))
    token = tmp_path / "token.json"
    _write_token(token, expires_in=datetime.timedelta(hours=1))
    monkeypatch.setattr(google_auth, "CREDENTIALS_FILE", secrets)
    monkeypatch.setattr(google_auth, "TOKEN_FILE", token)
    return token


def by_name(status):
    return {row["name"]: row for row in status}


async def follow_up_events(web, thread, question, until="turn_ended"):
    """The events of a Follow-up, from a stream opened before it was asked."""
    async with web.events(thread) as stream:
        await stream.next()  # state
        assert (await web.ask(thread, question)).status_code == 202
        return await stream.until(until)


async def test_a_google_token_that_dies_shows_dead_with_its_login_command_and_a_fresh_one_alive(serve, google_token):
    web = await serve({"q1": ["one", "two", "three"]}, logins=Logins([google_login()]))
    assert by_name((await web.client.get("/api/logins")).json())["Google"]["alive"] is True
    thread = await web.start("q1")
    async with web.events(thread) as stream:
        await stream.settled()

    google_token.unlink()  # the token died while the server runs
    seen = await follow_up_events(web, thread, "q2")
    statuses = [data["logins"] for name, data in seen if name == "login_status"]
    assert [by_name(s)["Google"]["alive"] for s in statuses] == [False]
    assert by_name(statuses[0])["Google"]["command"] == GOOGLE_LOGIN_COMMAND
    assert by_name((await web.client.get("/api/logins")).json())["Google"]["alive"] is False

    _write_token(google_token, expires_in=datetime.timedelta(hours=1))  # the owner logged in again
    seen = await follow_up_events(web, thread, "q3")
    statuses = [data["logins"] for name, data in seen if name == "login_status"]
    assert [by_name(s)["Google"]["alive"] for s in statuses] == [True]


async def test_a_slow_or_hanging_check_does_not_hold_a_turn_up_beyond_the_wait(serve):
    async def hangs():
        await asyncio.Event().wait()
    logins = Logins([Integration("Slow", "log in", hangs)], check_timeout_s=3, turn_wait_s=0.2)
    web = await serve({"q1": ["one", "two"]}, logins=logins)

    began = time.monotonic()
    thread = await web.start("q1")
    async with web.events(thread) as stream:
        seen = await stream.settled()
    assert seen[-1][1]["status"] == "idle"
    seen = await follow_up_events(web, thread, "q2")  # the hung refresh is still running
    assert seen[-1][1]["outcome"] == "answered"
    assert time.monotonic() - began < 1.5
    assert by_name((await web.client.get("/api/logins")).json())["Slow"]["alive"] is True  # cached


async def test_claude_code_shows_dead_with_claude_auth_login_when_the_cli_is_logged_out(serve, monkeypatch, tmp_path):
    replies = tmp_path / "replies.json"
    replies.write_text(json.dumps([{"loggedIn": False}]))
    monkeypatch.setenv(fake_cli.CALLS_ENV, str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv(fake_cli.REPLIES_ENV, str(replies))
    web = await serve({"q1": ["one"]}, logins=Logins([claude_code_login(fake_cli.binary())]))
    thread = await web.start("q1")
    async with web.events(thread) as stream:
        await stream.settled()

    claude = by_name((await web.client.get("/api/logins")).json())["Claude Code"]
    assert claude["alive"] is False
    assert claude["command"] == CLAUDE_CODE_LOGIN_COMMAND
    assert [call["args"] for call in fake_cli.recorded_calls(tmp_path / "calls.jsonl")] == [["auth", "status"]]


async def test_an_ms365_server_skipped_at_startup_is_loaded_once_its_login_passes(serve, google_token, monkeypatch,
                                                                                  tmp_path):
    switch = FailureSwitch(tmp_path / "ms365-failure")
    monkeypatch.setenv(FAILURE_FILE_ENV, str(switch.path))
    switch.set(Failure.LOGGED_OUT)
    servers = [ms365_fixture_server()]
    mcp_tools, notices = await load_mcp_tools(servers)
    assert mcp_tools == []  # skipped at startup for its login
    logins = startup_logins(servers, tools=[*TOOLS, *mcp_tools], notices=notices)
    assert [row["name"] for row in logins.status()] == ["Google", "ms365"]
    logins.turn_wait_s = 30  # starting the stand-in server is slow; here each turn waits for its checks
    web = await serve({"q1": ["one", "two", ai("", ("c1", "ms365_list-mail-messages", {"top": 1})), "three"]},
                      logins=logins)
    ms365 = by_name((await web.client.get("/api/logins")).json())["ms365"]
    assert (ms365["alive"], ms365["command"]) == (False, LOGIN.command)

    thread = await web.start("q1")  # still logged out: still skipped
    async with web.events(thread) as stream:
        await stream.settled()
    assert not any(t.name.startswith("ms365_") for t in web.app.state.turns.tools)

    switch.clear()  # the owner logged in to MS365
    seen = await follow_up_events(web, thread, "q2")
    assert [by_name(data["logins"])["ms365"]["alive"] for name, data in seen if name == "login_status"] == [True]

    seen = await follow_up_events(web, thread, "q3")  # a later turn has its tools
    step, = [data["step"] for name, data in seen if name == "step_finished"]
    assert step["name"] == "ms365_list-mail-messages" and not step["error"], step


async def test_an_mcp_server_that_failed_to_start_for_another_reason_is_not_retried(tmp_path):
    starts = tmp_path / "starts"
    crashing = McpServer(
        name="crashy",
        connection={"transport": "stdio", "command": sys.executable,
                    "args": ["-c", f"open({str(starts)!r}, 'a').write('x'); raise SystemExit(1)"]},
        login=LoginCheck(service="Crashy", command="crashy login", check_tool="verify-login"),
    )
    mcp_tools, notices = await load_mcp_tools([crashing])
    assert mcp_tools == [] and "failed to start" in notices[0]
    logins = startup_logins([crashing], tools=[], notices=notices)
    logins.turn_wait_s = 30

    await logins.refresh_for_turn()

    assert starts.read_text() == "x"  # started once, at startup: no login to wait for, so no retry
    crashy = by_name(logins.status())["crashy"]
    assert (crashy["alive"], crashy["detail"]) == (False, notices[0])
