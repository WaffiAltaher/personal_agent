# src/agent/live_smoke.py
"""Read-only check that MS365 and Informer answer. It never creates a Draft."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from dotenv import dotenv_values
from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from agent.config import Settings
from agent.tools.informer import informer_server
from agent.tools.mcp_loader import McpServer, load_mcp_tools
from agent.tools.ms365_mcp import ms365_server

# These are optional on Settings, so an unset process variable would otherwise fill them
# (tests set dummy MS365 ids). The .env file is the only source for a live probe.
_FILE_ONLY_CREDENTIALS = (
    "ms365_mcp_client_id",
    "ms365_mcp_tenant_id",
    "ms365_mcp_expected_username",
    "informer_api_key",
    "informer_security_code",
)

# The only calls this check makes. Draft tools are not here, so no Draft is created.
_READS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("ms365_list-mail-messages", {"top": 1}, "value"),  # mail
    ("ms365_list-calendar-events", {"top": 1}, "value"),  # calendar
    ("ms365_list-outlook-contacts", {"top": 1}, "value"),  # contacts
    ("informer_list_relations", {}, "relations"),  # Relations
    ("informer_list_sales_invoices", {}, "invoices"),  # Sales invoices
)


@dataclass(frozen=True)
class SmokeResult:
    status: Literal["ok", "blocked", "failed"]
    reason: str = ""
    payloads: Mapping[str, Any] = field(default_factory=dict)


async def run_live_smoke(
    *,
    servers: list[McpServer] | None = None,
    timeout_s: float = 90,
) -> SmokeResult:
    """Probe the configured servers.

    A missing MS365 login, or a probe that does not finish within `timeout_s`
    (a keychain prompt or a server that never answers), is blocked. Cancellation
    closes the MCP stdio session, which kills a hung server process.
    """
    try:
        return await asyncio.wait_for(_probe(servers), timeout_s)
    except TimeoutError:
        return SmokeResult(
            status="blocked",
            reason=(
                f"the probe did not finish within {timeout_s:g}s; "
                "a headless keychain or login wait was cut off"
            ),
        )


def _live_servers() -> list[McpServer] | SmokeResult:
    """Real MS365 and Informer servers from the `.env` file, not `os.environ`.

    Same pair as `mcp_servers(fixtures=False)`, with Settings built from the file
    values passed as constructor kwargs so process-environment dummies cannot hide them.
    """
    env_file = Path(".env")
    if not env_file.is_file():
        return SmokeResult(
            status="blocked",
            reason=".env is missing, so live MS365 and Informer credentials cannot be loaded",
        )
    raw = dotenv_values(env_file)
    known = set(Settings.model_fields)
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        field_name = (key or "").lower()
        if field_name in known and value is not None:
            kwargs[field_name] = value
    for name in _FILE_ONLY_CREDENTIALS:
        kwargs[name] = raw.get(name.upper()) or None
    try:
        settings = Settings(_env_file=None, **kwargs)
    except ValidationError as exc:
        fields = ", ".join(str(err["loc"][0]) for err in exc.errors() if err.get("loc"))
        reason = "could not load settings from .env"
        if fields:
            reason = f"{reason} ({fields})"
        return SmokeResult(status="failed", reason=reason)
    return [ms365_server(settings), informer_server(settings)]


async def _probe(servers: list[McpServer] | None) -> SmokeResult:
    if servers is None:
        loaded = _live_servers()
        if isinstance(loaded, SmokeResult):
            return loaded
        servers = loaded
    tools, notices = await load_mcp_tools(servers)
    login_notices = [notice for notice in notices if _login_problem(notice)]
    if login_notices:
        return SmokeResult(status="blocked", reason="\n".join(login_notices))
    if notices:
        return SmokeResult(status="failed", reason="\n".join(notices))

    by_name = {tool.name: tool for tool in tools}
    payloads: dict[str, Any] = {}
    for name, args, collection in _READS:
        tool = by_name.get(name)
        if tool is None:
            return SmokeResult(status="failed", reason=f"{name} is not available")
        try:
            raw = await tool.ainvoke(args)
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if _login_problem(text):
                return SmokeResult(status="blocked", reason=text)
            return SmokeResult(status="failed", reason=f"{name} failed: {text}")
        body, problem = _collection(raw, collection)
        if problem is not None:
            if _login_problem(problem):
                return SmokeResult(status="blocked", reason=problem)
            return SmokeResult(status="failed", reason=f"{name} failed: {problem}")
        payloads[name] = body
    return SmokeResult(status="ok", payloads=MappingProxyType(payloads))


def _login_problem(text: str) -> bool:
    """Loader notice or tool text from a missing or expired MS365 login."""
    return "not logged in" in text or "No valid token found" in text


def _collection(raw: Any, key: str) -> tuple[dict[str, Any] | None, str | None]:
    """The parsed payload when `key` is a list (empty counts), or an error string."""
    if isinstance(raw, ToolMessage) and raw.status == "error":
        return None, _text(raw.content) or "tool error"
    text = _text(raw)
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None, text or "tool result was not JSON"
    if not isinstance(body, dict) or not isinstance(body.get(key), list):
        return None, text or f"no {key} collection"
    return body, None


def _text(raw: Any) -> str:
    if isinstance(raw, ToolMessage):
        raw = raw.content
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""
