"""Fail when a test function sits in a module pytest will never collect."""

import ast
import subprocess
import sys
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


def test_browser_journeys_carry_a_registered_marker_that_deselects_them(request):
    assert any(line.startswith("browser:") for line in request.config.getini("markers"))
    journeys = str(ROOT / "web" / "test_web_browser.py")
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "not browser", journeys],
        capture_output=True, text=True, cwd=ROOT.parent,
    ).stdout
    assert "test_web_browser.py::" not in collected and "deselected" in collected, collected
