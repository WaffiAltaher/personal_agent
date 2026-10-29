# src/fixture_world/claude_code.py
"""Stand-in Claude Code CLI: the Fixture world's `claude -p ... --output-format json`.

Tests point CLAUDE_CODE_BINARY at it (`binary()`), so the agent's `claude_code:` chat model
runs for real (process, environment, standard input, JSON result) without the real CLI.

Each call appends what it was given (arguments, environment, standard input, working
directory) as a JSON line to the file named by FIXTURE_WORLD_CLAUDE_CODE_CALLS; read it back
with `recorded_calls()`. It then prints the next scripted reply from the JSON list in the file
named by FIXTURE_WORLD_CLAUDE_CODE_REPLIES, the n-th call printing the n-th reply. A reply is
the result text, or a dict of fields laid over the CLI's success object (as Claude Code
2.1.310 prints it). With `--json-schema`, a result text that is a JSON object also becomes
`structured_output`, and a clean reply takes 2 turns (the StructuredOutput call and its
acknowledgement), as Claude Code 2.1.312 does. For `claude auth status` the reply is the status
JSON, printed as is.
A dict reply may instead script a failure: {"hang": true} never answers, `auth status` included
(see `hung_pids()`), and
"stdout", "stderr" and "exit_code" print raw output and set the exit status. SESSION_LIMIT is
the real subscription-limit result.

Installed as the `fixture-claude-code` script.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CALLS_ENV = "FIXTURE_WORLD_CLAUDE_CODE_CALLS"
REPLIES_ENV = "FIXTURE_WORLD_CLAUDE_CODE_REPLIES"

# A Claude Code subscription limit as it really happened on 2026-10-25 (HTTP 429, error type rate_limit).
SESSION_LIMIT = {
    "is_error": True,
    "api_error_status": 429,
    "result": "You've hit your session limit · resets 9:50pm (Europe/Amsterdam)",
}


def binary() -> str:
    """Path of the installed stand-in executable."""
    path = shutil.which("fixture-claude-code", path=str(Path(sys.executable).parent))
    if path is None:
        raise RuntimeError("fixture-claude-code is not installed; run `uv sync`.")
    return path


def recorded_calls(path: Path) -> list[dict]:
    """Every call recorded in `path`, oldest first."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def hung_pids(calls_path: Path) -> list[int]:
    """Process IDs of a hung call (the stand-in and the child it started), or [] if none hung."""
    path = calls_path.with_suffix(".hung")
    return json.loads(path.read_text()) if path.exists() else []


def _success(result: str) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "result": result,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "session_id": "00000000-0000-0000-0000-000000000000",
        "usage": {"input_tokens": 0, "output_tokens": 0,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        "modelUsage": {},
        "permission_denials": [],
    }


def main() -> None:
    calls_path = Path(os.environ[CALLS_ENV])
    index = len(recorded_calls(calls_path))
    with calls_path.open("a") as f:
        f.write(json.dumps({
            "args": sys.argv[1:], "env": dict(os.environ), "stdin": sys.stdin.read(), "cwd": os.getcwd(),
        }) + "\n")

    reply = json.loads(Path(os.environ[REPLIES_ENV]).read_text())[index]
    if isinstance(reply, str):
        reply = {"result": reply}
    if reply.get("hang"):
        # Never answers, like a stuck CLI that has started a child of its own; `hung_pids()` reads both.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        calls_path.with_suffix(".hung").write_text(json.dumps([os.getpid(), child.pid]))
        time.sleep(600)
    if sys.argv[1:3] == ["auth", "status"]:
        print(json.dumps(reply))
        return
    # Failures: "stdout" is printed as is instead of a result, "stderr" goes to standard error,
    # "exit_code" is the exit status.
    sys.stderr.write(reply.pop("stderr", ""))
    exit_code = reply.pop("exit_code", 0)
    if "stdout" in reply:
        print(reply.pop("stdout"))
    else:
        result = {**_success(""), **(_structured(reply.get("result", "")) if "--json-schema" in sys.argv else {}), **reply}
        print(json.dumps(result))
    sys.exit(exit_code)


def _structured(result: str) -> dict:
    """The fields --json-schema adds: the result text as an object, if it is one, and 2 turns."""
    try:
        value = json.loads(result)
    except json.JSONDecodeError:
        value = None
    return {"structured_output": value if isinstance(value, dict) else None, "num_turns": 2}


if __name__ == "__main__":
    main()
