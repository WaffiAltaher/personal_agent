# src/agent/auth/claude_code.py
"""
Claude Code login check (ADR-016).

A `claude_code:` model runs on the owner's claude.ai subscription through the Claude Code CLI.
Before a real CLI run, startup asks the CLI for its login status (`claude auth status`, which
uses no model usage), under the same environment rules as a model call: the API-key variables
are removed, so an exported key can't make the login look different from what the run will use.
"""

import json
import subprocess

from agent.claude_code_model import claude_code_env

CLAUDE_CODE_LOGIN_COMMAND = "claude auth login"
LOGIN_CHECK_TIMEOUT_S = 30


class ClaudeCodeLoginRequired(RuntimeError):
    """Claude Code is not logged in with a claude.ai subscription."""


class ClaudeCodeLoginCheckTimeout(RuntimeError):
    """Claude Code did not answer the login status check in time."""


def check_claude_code_login(binary: str) -> None:
    """Verify a claude.ai login before a real CLI run.

    Raises:
        FileNotFoundError: if the Claude Code binary can't be found
        ClaudeCodeLoginRequired: if the CLI is logged out or logged in another way (an API key)
        ClaudeCodeLoginCheckTimeout: if the CLI does not answer within LOGIN_CHECK_TIMEOUT_S
    """
    try:
        status_call = subprocess.run(
            [binary, "auth", "status"], capture_output=True, text=True, env=claude_code_env(),
            timeout=LOGIN_CHECK_TIMEOUT_S,
        )
    except FileNotFoundError:
        raise FileNotFoundError(f"Claude Code not found on PATH ({binary}). Install it, or set CLAUDE_CODE_BINARY.") from None
    except subprocess.TimeoutExpired:
        raise ClaudeCodeLoginCheckTimeout(
            f"Claude Code did not answer `claude auth status` within {LOGIN_CHECK_TIMEOUT_S:g} s. "
            "Check that `claude auth status` works in a terminal, then restart the agent."
        ) from None
    try:
        status = json.loads(status_call.stdout)
    except json.JSONDecodeError:
        status = {}
    if not (isinstance(status, dict) and status.get("loggedIn") is True and status.get("authMethod") == "claude.ai"):
        raise ClaudeCodeLoginRequired(
            "Claude Code is not logged in with a claude.ai subscription. "
            f"Run `{CLAUDE_CODE_LOGIN_COMMAND}`, then restart the agent."
        )
