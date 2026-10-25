# src/agent/auth/claude_code.py
"""
Claude Code login check (ADR-016).

A `claude_code:` model runs on the owner's claude.ai subscription through the Claude Code CLI.
Before a real CLI run, startup asks the CLI for its login status (`claude auth status`, which
uses no model usage), under the same environment rules as a model call: the API-key variables
are removed, so an exported key can't make the login look different from what the run will use.
"""

import json
import os
import subprocess

from agent.claude_code_model import _REMOVED_ENV

CLAUDE_CODE_LOGIN_COMMAND = "claude auth login"


class ClaudeCodeLoginRequired(RuntimeError):
    """Claude Code is not logged in with a claude.ai subscription."""


def check_claude_code_login(binary: str) -> None:
    """Verify a claude.ai login before a real CLI run.

    Raises:
        FileNotFoundError: if the Claude Code binary can't be found
        ClaudeCodeLoginRequired: if the CLI is logged out or logged in another way (an API key)
    """
    env = {k: v for k, v in os.environ.items() if k not in _REMOVED_ENV}
    try:
        done = subprocess.run([binary, "auth", "status"], capture_output=True, text=True, env=env, timeout=30)
    except FileNotFoundError:
        raise FileNotFoundError(f"Claude Code not found on PATH ({binary}). Install it, or set CLAUDE_CODE_BINARY.") from None
    try:
        status = json.loads(done.stdout)
    except json.JSONDecodeError:
        status = {}
    if not (isinstance(status, dict) and status.get("loggedIn") is True and status.get("authMethod") == "claude.ai"):
        raise ClaudeCodeLoginRequired(
            "Claude Code is not logged in with a claude.ai subscription. "
            f"Run `{CLAUDE_CODE_LOGIN_COMMAND}`, then restart the agent."
        )
