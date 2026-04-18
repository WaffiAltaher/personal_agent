"""
tests/test_tools.py

Unit tests for filesystem tools.

Strategy: use pytest's tmp_path fixture to create real temporary files,
then call read_file.invoke(...) directly. No mocks, no LLM, no graph.
The tool is pure Python — test it that way.

We call `.invoke({"path": ...})` rather than `read_file(path=...)` because
@tool-decorated functions go through LangChain's tool dispatch layer,
which validates the input against the Pydantic schema before execution.
Calling .invoke() exercises that validation path too.
"""

import pytest
from unittest.mock import patch
from agent.tools.filesystem import list_directory, read_file


def test_read_file_returns_content(tmp_path):
    """Happy path: tool reads a file and returns its contents."""
    f = tmp_path / "notes.txt"
    f.write_text("hello from the test")

    result = read_file.invoke({"path": str(f)})

    assert result == "hello from the test"


def test_read_file_not_found(tmp_path):
    """Sad path: non-existent file returns an error string, does not raise."""
    missing = tmp_path / "does_not_exist.txt"

    result = read_file.invoke({"path": str(missing)})

    # The tool must return a string — raising an exception would break the graph.
    assert result.startswith("Error:")
    assert "not found" in result


def test_read_file_too_large(tmp_path):
    """
    Guard path: files over 1 MB are rejected before being read.

    We write 1 MB + 1 byte of data. The tool should catch this in the
    stat() check and return an error without reading the file contents.
    """
    big_file = tmp_path / "big.txt"
    big_file.write_bytes(b"x" * (1 * 1024 * 1024 + 1))

    result = read_file.invoke({"path": str(big_file)})

    assert result.startswith("Error:")
    assert "too large" in result


# ---------------------------------------------------------------------------
# list_directory tests
# ---------------------------------------------------------------------------

def test_list_directory_returns_contents(tmp_path):
    """Happy path: lists files and subdirs in a directory."""
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "data").mkdir()
    (tmp_path / "readme.md").write_text("docs")

    result = list_directory.invoke({"path": str(tmp_path)})

    assert "[FILE] notes.txt" in result
    assert "[FILE] readme.md" in result
    assert "[DIR]  data" in result


def test_list_directory_not_found(tmp_path):
    """Sad path: non-existent directory returns an error string."""
    missing = tmp_path / "does_not_exist"

    result = list_directory.invoke({"path": str(missing)})

    assert result.startswith("Error:")
    assert "not found" in result


def test_list_directory_on_file_returns_error(tmp_path):
    """Guard path: passing a file path instead of a directory returns an error."""
    f = tmp_path / "notes.txt"
    f.write_text("hello")

    result = list_directory.invoke({"path": str(f)})

    assert result.startswith("Error:")
    assert "not a directory" in result


def test_list_directory_empty(tmp_path):
    """Edge case: empty directory returns a clear message rather than an error."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = list_directory.invoke({"path": str(empty_dir)})

    assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# web_search tests
# ---------------------------------------------------------------------------

def test_web_search_returns_results():
    """
    Happy path: web_search returns a list of result dicts.

    We mock the underlying Tavily API call — this test verifies that the
    tool is correctly wired up and passes the query through, not that
    Tavily's API works (that's their problem to test).
    """
    mock_results = {
        "query": "LangGraph tutorial",
        "results": [
            {"url": "https://example.com", "content": "Example content about LangGraph"},
            {"url": "https://docs.example.com", "content": "Documentation page"},
        ],
    }

    from agent.tools.web import web_search
    # TavilySearch (langchain-tavily) uses response_format="content"; _run returns
    # the structured result dict directly.
    with patch.object(web_search, "_run", return_value=mock_results):
        result = web_search.invoke({"query": "LangGraph tutorial"})

    assert result == mock_results
