# src/fixture_world/claude_code.py
"""Stand-in Claude Code CLI: the Fixture world's `claude -p ... --output-format json`.

Tests point CLAUDE_CODE_BINARY at it (`binary()`), so the agent's `claude_code:` chat model
runs for real (process, environment, standard input, JSON result) without the real CLI.

Each call appends what it was given (arguments, environment, standard input, working
directory) as a JSON line to the file named by FIXTURE_WORLD_CLAUDE_CODE_CALLS; read it back
with `recorded_calls()`. It then prints the next scripted reply from the JSON list in the file
named by FIXTURE_WORLD_CLAUDE_CODE_REPLIES, the n-th call printing the n-th reply. A reply is
the result text, or a dict of fields laid over the CLI's success object (as Claude Code
2.1.310 prints it). For `claude auth status` the reply is the status JSON, printed as is.

Installed as the `fixture-claude-code` script.
"""

import json
import os
import shutil
import sys
from pathlib import Path

CALLS_ENV = "FIXTURE_WORLD_CLAUDE_CODE_CALLS"
REPLIES_ENV = "FIXTURE_WORLD_CLAUDE_CODE_REPLIES"


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
    if sys.argv[1:3] == ["auth", "status"]:
        print(json.dumps(reply))
        return
    if isinstance(reply, str):
        reply = {"result": reply}
    print(json.dumps({**_success(""), **reply}))


if __name__ == "__main__":
    main()
