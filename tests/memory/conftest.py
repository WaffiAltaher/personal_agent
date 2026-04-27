# tests/memory/conftest.py
"""Session-level fixture that ensures stress test data files exist before tests run."""

import importlib.util
from pathlib import Path

import pytest


def _load_generator():
    script = Path(__file__).resolve().parents[2] / "scripts" / "generate_stress_context.py"
    spec = importlib.util.spec_from_file_location("generate_stress_context", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session", autouse=True)
def ensure_stress_fixtures():
    """Generate fixture files once per test session if any are missing."""
    fixtures_dir = Path(__file__).resolve().parents[1] / "fixtures"
    needed = (
        "long_conversation.json",
        "bloated_tool_result.json",
        "large_memory_injection.json",
    )
    if not all((fixtures_dir / name).exists() for name in needed):
        gen = _load_generator()
        gen.generate_all(fixtures_dir)
