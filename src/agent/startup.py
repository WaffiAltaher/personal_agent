"""
startup.py — startup steps both front ends (the CLI and the web server) run, with the same messages.

Each front end runs them in this order: build the model (``create_chat_model``), ``check_langfuse()``,
``check_logins()`` (real data only), load tools (``load_all_tools``), then ``print_notices(...)``.
A check that fails prints ``Cannot start: ...`` and exits with status 1.
"""

import sys
from typing import NoReturn

from agent.auth.claude_code import ClaudeCodeLoginCheckTimeout, ClaudeCodeLoginRequired, check_claude_code_login
from agent.auth.google import GoogleLoginRequired, check_google_login
from agent.chat_model import is_claude_code_model
from agent.config import settings
from agent.tracing import verify_connection


def cannot_start(reason: object) -> NoReturn:
    """Stop startup, saying why."""
    print(f"Cannot start: {reason}")
    sys.exit(1)


def check_langfuse() -> bool:
    """Verify Langfuse is reachable before any work. If it isn't, say which address was tried
    and run untraced: observability failing shouldn't block the agent."""
    connected = verify_connection()
    if not connected:
        print(f"Warning: Langfuse connection failed at {settings.langfuse_base_url}. "
              "Traces will not be recorded.")
    return connected


def check_logins() -> None:
    """Stop unless the Google login, and for a ``claude_code:`` agent or judge model the Claude
    Code login, is alive. Each message names the command that fixes it."""
    try:
        check_google_login()
    except (GoogleLoginRequired, FileNotFoundError) as exc:
        cannot_start(exc)
    # A claude_code: agent or judge model runs on the Claude Code login; check it the same way.
    if any(is_claude_code_model(m) for m in (settings.model_name, settings.eval_judge_model)):
        try:
            check_claude_code_login(settings.claude_code_binary)
        except (ClaudeCodeLoginRequired, ClaudeCodeLoginCheckTimeout, FileNotFoundError) as exc:
            cannot_start(exc)


def print_notices(notices: list[str]) -> None:
    """An unavailable integration doesn't stop the run; say which one and why."""
    for notice in notices:
        print(f"Notice: {notice}")
