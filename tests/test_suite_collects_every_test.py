"""Fail when a test function sits in a module pytest will never collect."""

import ast
from pathlib import Path

ROOT = Path(__file__).parent


def test_every_test_function_lives_in_a_collected_module():
    missed = []
    for path in ROOT.rglob("*.py"):
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            for node in tree.body
        ):
            missed.append(str(path.relative_to(ROOT)))
    assert missed == []
