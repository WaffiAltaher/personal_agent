"""
Google login at startup (real CLI mode) and the re-login command.

Seam: the CLI driver and agent.auth.google public behaviour. No real Google APIs or browsers.
"""

import datetime
import json
import sys
from contextlib import asynccontextmanager

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import agent.auth.google as google_auth
import agent.cli as cli
from agent.auth.google import GOOGLE_LOGIN_COMMAND, SCOPES
from agent.tools.gmail import search_gmail


MINIMAL_CLIENT_SECRETS = {
    "installed": {
        "client_id": "test-client-id",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def _write_client_secrets(path):
    path.write_text(json.dumps(MINIMAL_CLIENT_SECRETS))


def _expired_token(path) -> Credentials:
    creds = Credentials(
        token="access",
        refresh_token="refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client-id",
        client_secret="test-secret",
        scopes=SCOPES,
    )
    creds.expiry = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    path.write_text(creds.to_json())
    return creds


@pytest.fixture
def google_paths(monkeypatch, tmp_path):
    creds_file = tmp_path / "google_credentials.json"
    token_file = tmp_path / "token.json"
    _write_client_secrets(creds_file)
    monkeypatch.setattr(google_auth, "CREDENTIALS_FILE", creds_file)
    monkeypatch.setattr(google_auth, "TOKEN_FILE", token_file)
    return creds_file, token_file


@pytest.fixture
def run_cli(monkeypatch, scripted_model):
    """Minimal CLI harness; real-mode runs bind real Google tools unless load_all_tools is stubbed."""
    seen = {"check_calls": 0}

    def reply(_messages):
        return AIMessage(content="ok")

    async def load_all_tools(*, fixtures=False):
        return [], []

    @asynccontextmanager
    async def get_checkpointer():
        yield InMemorySaver()

    real_check = google_auth.check_google_login

    def check_and_count():
        seen["check_calls"] += 1
        return real_check()

    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([reply]))
    monkeypatch.setattr(cli, "verify_connection", lambda: True)
    monkeypatch.setattr(cli, "get_callback_handler", lambda **kwargs: BaseCallbackHandler())
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(cli, "log_run_to_memory", lambda *args: None)
    monkeypatch.setattr(cli, "flush_traces", lambda: None)
    monkeypatch.setattr(google_auth, "check_google_login", check_and_count)
    monkeypatch.setattr(cli, "check_google_login", check_and_count)

    async def run(*args):
        monkeypatch.setattr(sys, "argv", ["agent.cli", *args])
        await cli.main()
        return seen

    return run


@pytest.mark.asyncio
async def test_real_mode_startup_with_dead_refresh_token_deletes_token_and_fails_with_relogin_command(
        run_cli, google_paths, monkeypatch, capsys):
    _, token_file = google_paths
    _expired_token(token_file)

    def refresh(_self, _request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", refresh)

    with pytest.raises(SystemExit) as exc:
        await run_cli("What is in my inbox?")

    assert exc.value.code == 1
    assert not token_file.exists()
    out = capsys.readouterr().out
    assert GOOGLE_LOGIN_COMMAND in out


@pytest.mark.asyncio
async def test_real_mode_startup_with_no_token_fails_without_opening_a_browser(
        run_cli, google_paths, monkeypatch, capsys):
    creds_file, token_file = google_paths
    assert creds_file.exists()
    assert not token_file.exists()

    class MustNotOpenBrowser:
        @staticmethod
        def from_client_secrets_file(*_args, **_kwargs):
            raise AssertionError("browser OAuth flow must not run during startup")

    monkeypatch.setattr(google_auth, "InstalledAppFlow", MustNotOpenBrowser)

    with pytest.raises(SystemExit) as exc:
        await run_cli("What is in my inbox?")

    assert exc.value.code == 1
    assert GOOGLE_LOGIN_COMMAND in capsys.readouterr().out


@pytest.mark.asyncio
async def test_fixture_world_startup_never_checks_google_login(run_cli, google_paths, monkeypatch):
    creds_file, token_file = google_paths
    assert not token_file.exists()

    class MustNotOpenBrowser:
        @staticmethod
        def from_client_secrets_file(*_args, **_kwargs):
            raise AssertionError("browser OAuth flow must not run in fixture mode")

    monkeypatch.setattr(google_auth, "InstalledAppFlow", MustNotOpenBrowser)

    seen = await run_cli("--fixtures", "What day is it?")
    assert seen["check_calls"] == 0


def test_gmail_tool_does_not_open_browser_when_login_is_missing(google_paths, monkeypatch):
    creds_file, token_file = google_paths
    assert creds_file.exists()
    assert not token_file.exists()

    class MustNotOpenBrowser:
        @staticmethod
        def from_client_secrets_file(*_args, **_kwargs):
            raise AssertionError("browser OAuth flow must not run from a tool call")

    monkeypatch.setattr(google_auth, "InstalledAppFlow", MustNotOpenBrowser)

    result = search_gmail.invoke({"query": "in:inbox"})
    assert result.startswith("Error:")
    assert GOOGLE_LOGIN_COMMAND in result


def test_relogin_command_saves_token_via_browser_flow(google_paths, monkeypatch):
    _, token_file = google_paths
    assert not token_file.exists()

    fresh = Credentials(
        token="new-access",
        refresh_token="new-refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client-id",
        client_secret="test-secret",
        scopes=SCOPES,
    )

    class FakeFlow:
        @staticmethod
        def from_client_secrets_file(_path, _scopes):
            return FakeFlow()

        def run_local_server(self, port=0):
            return fresh

    monkeypatch.setattr(google_auth, "InstalledAppFlow", FakeFlow)

    google_auth.login_via_browser()

    assert token_file.exists()
    loaded = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    assert loaded.token == "new-access"
