"""
Filesystem tools for the personal data agent.

These are the simplest possible tools — no auth, no network, no state.
Good for learning the tool definition pattern before adding complexity.
"""

import os
from pathlib import Path
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field


# --- Input schema ---
# We define this explicitly (rather than relying on inferred types) because:
# 1. Field descriptions end up in the JSON schema the LLM sees — they matter.
# 2. We can add validators here later without touching the function signature.
# 3. It's the pattern we'll use for every tool going forward.

class ReadFileInput(BaseModel):
    path: str = Field(
        description=(
            "Absolute or relative path to the file to read. "
            "Use this tool only for plain-text files (e.g. .txt, .md, .py, .json). "
            "Do not use for binary files."
        )
    )


@tool("read_file", args_schema=ReadFileInput)
def read_file(path: str) -> str:
    """
    Read the contents of a plain-text file and return them as a string.
    Use this when you need to inspect a local file's contents.

    Limits: supports UTF-8 text files up to 1 MB. Binary files are not supported.
    On failure (missing path, too large, wrong type, permission denied, decode
    error) the tool returns a string beginning with "Error:" instead of raising.
    Read that error and adjust your next step (e.g. list the parent directory
    to find the correct path) rather than retrying blindly.
    """
    try:
        file_path = Path(path).expanduser().resolve()

        # Sanity checks before we open anything
        if not file_path.exists():
            return f"Error: file not found: {file_path}"

        if not file_path.is_file():
            return f"Error: path exists but is not a file: {file_path}"

        # 1 MB guard — protect against accidentally feeding huge files into context
        max_bytes = 1 * 1024 * 1024
        size = file_path.stat().st_size
        if size > max_bytes:
            return (
                f"Error: file is too large to read ({size:,} bytes). "
                f"Maximum allowed is {max_bytes:,} bytes (1 MB). "
                "Consider reading a specific section instead."
            )

        return file_path.read_text(encoding="utf-8")

    except PermissionError:
        return f"Error: permission denied reading {path}"
    except UnicodeDecodeError:
        return (
            f"Error: could not decode {path} as UTF-8. "
            "This tool only supports plain-text files."
        )
    except Exception as e:
        # Broad catch is intentional: the agent must get a ToolMessage back,
        # not a Python traceback that halts the graph.
        return f"Error reading file: {type(e).__name__}: {e}"


# --- list_directory tool ---

class ListDirectoryInput(BaseModel):
    path: str = Field(
        description=(
            "Absolute or relative path to the directory to list. "
            "Returns the names of all files and subdirectories at the top level "
            "of the given path. Does not recurse into subdirectories."
        )
    )


@tool("list_directory", args_schema=ListDirectoryInput)
def list_directory(path: str) -> str:
    """
    List the files and subdirectories at the top level of a directory.
    Use this to explore what files exist before deciding which ones to read,
    or to resolve a path when you are unsure whether a file exists.

    Returns a formatted text listing with `[DIR]` and `[FILE]` prefixes.
    The listing is not recursive — call this tool again on a subdirectory
    to descend into it.

    On failure (missing path, not a directory, permission denied) the tool
    returns a string beginning with "Error:" instead of raising.
    """
    try:
        dir_path = Path(path).expanduser().resolve()

        if not dir_path.exists():
            return f"Error: path not found: {dir_path}"

        if not dir_path.is_dir():
            return f"Error: path exists but is not a directory: {dir_path}"

        entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))

        if not entries:
            return f"Directory is empty: {dir_path}"

        lines = [f"Contents of {dir_path}:", ""]
        for entry in entries:
            prefix = "[DIR] " if entry.is_dir() else "[FILE]"
            lines.append(f"  {prefix} {entry.name}")

        return "\n".join(lines)

    except PermissionError:
        return f"Error: permission denied accessing {path}"
    except Exception as e:
        return f"Error listing directory: {type(e).__name__}: {e}"

# --- Eval stand-ins ---
# Same names, arguments and descriptions as the tools above, but confined to the folder named
# by FILES_ROOT_ENV (an eval run's own Downloads folder): a relative path resolves inside it,
# and a path outside it is reported as not found. The eval harness binds these in place of the
# real tools, so a scenario never reads the owner's real files.

FILES_ROOT_ENV = "FIXTURE_WORLD_FILES_ROOT"


def _inside_files_root(path: str) -> Path | None:
    """`path` resolved inside the files root, or None if it is outside it or no root is set."""
    root = os.environ.get(FILES_ROOT_ENV)
    if not root:
        return None
    root_path = Path(root).resolve()
    candidate = Path(path).expanduser()
    resolved = (candidate if candidate.is_absolute() else root_path / candidate).resolve()
    return resolved if resolved.is_relative_to(root_path) else None


def _read_fixture_file(path: str) -> str:
    resolved = _inside_files_root(path)
    if resolved is None:
        return f"Error: file not found: {Path(path).expanduser()}"
    return read_file.func(str(resolved))


def _list_fixture_directory(path: str) -> str:
    resolved = _inside_files_root(path)
    if resolved is None:
        return f"Error: path not found: {Path(path).expanduser()}"
    return list_directory.func(str(resolved))


fixture_read_file = StructuredTool.from_function(
    func=_read_fixture_file,
    name=read_file.name,
    description=read_file.description,
    args_schema=ReadFileInput,
)

fixture_list_directory = StructuredTool.from_function(
    func=_list_fixture_directory,
    name=list_directory.name,
    description=list_directory.description,
    args_schema=ListDirectoryInput,
)
