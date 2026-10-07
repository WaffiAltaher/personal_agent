# tests/conftest.py
"""Dummy credentials so the suite runs without a real .env (e.g. in a fresh worktree)."""

import os

for _key in (
    "GOOGLE_API_KEY",
    "TAVILY_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "MS365_MCP_CLIENT_ID",
    "MS365_MCP_TENANT_ID",
):
    os.environ.setdefault(_key, "test-dummy")
