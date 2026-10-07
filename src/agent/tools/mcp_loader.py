# src/agent/tools/mcp_loader.py
"""
One loader for every MCP server the agent uses (MS365, Informer, ...).

Each server is described by an McpServer and loaded through langchain-mcp-adapters
with its name as the tool prefix ("ms365_get-calendar-view"). Servers are optional
and isolated: one that isn't configured, or fails to start, is skipped with a notice
naming it and why, and the agent starts with the rest.

Each server's tools are classified (read or Write action, failing closed) here, at
load time, with that server's own trust settings.

Failures at the boundary never take the agent down:
- at startup, a server that fails to start, or whose login is missing or expired
  (LoginCheck), is skipped with a notice; a login notice names the login command;
- in a run, a tool error reported through MCP reaches the model as an error ToolMessage.
  One that matches the server's `transient_errors`, or a server that closes the connection
  (crashed, or died before answering), is raised as a TransientMcpError instead, so the
  graph's retry policy retries it (read tools only) and its fallback reports it. One that
  matches `LoginCheck.error_patterns` tells the model which login command the user needs.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_mcp_adapters.sessions import Connection
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, TextContent

from agent.tools.classification import classify_mcp_tools

logger = logging.getLogger(__name__)


class TransientMcpError(Exception):
    """A transient failure at the MCP boundary; the graph's retry policy retries it on read tools."""


class LoginRequired(Exception):
    """The server's login is missing or expired."""


@dataclass(frozen=True)
class LoginCheck:
    """How to tell that a server's login is missing or expired, and how the user logs in."""

    service: str  # what the user logs in to, e.g. "Microsoft 365"
    command: str  # the login command shown to the user
    check_tool: str  # server tool (unprefixed, may be hidden) called at startup: an error or {"success": false} ⇒ not logged in
    error_patterns: tuple[str, ...] = ()  # regexes: a tool error matching one means the login is missing or expired


@dataclass(frozen=True)
class McpServer:
    """How to reach one MCP server, and which of its tools the model may see."""

    name: str  # also the tool-name prefix: "<name>_<tool>"
    connection: Connection | None  # None when the server isn't configured
    unavailable_reason: str = ""  # why connection is None, shown to the user
    hidden_tools: frozenset[str] = frozenset()  # server tool names (unprefixed) never bound
    read_allowlist: frozenset[str] = frozenset()  # server tool names (unprefixed) classified read
    trust_read_only_hint: bool = False  # classify tools annotated readOnlyHint as read
    login: LoginCheck | None = None  # checked at startup; None when the server needs no login
    transient_errors: tuple[str, ...] = ()  # regexes: a tool error matching one is transient (retryable)


def _text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def _check_login(client: MultiServerMCPClient, server: McpServer, login: LoginCheck) -> None:
    async with client.session(server.name) as session:
        result = await session.call_tool(login.check_tool, {})
    text = _text(result)
    try:
        status = json.loads(text)
    except ValueError:
        status = None
    if result.isError or (isinstance(status, dict) and status.get("success") is False):
        detail = status.get("message") or status.get("error") if isinstance(status, dict) else text
        raise LoginRequired(f"not logged in to {login.service} ({detail}). "
                            f"Log in with `{login.command}`, then restart the agent.")


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _connection_closed(exc: BaseException) -> bool:
    """The server went away mid-call: it crashed, or died before answering (possibly inside a TaskGroup)."""
    if isinstance(exc, BaseExceptionGroup):
        return all(_connection_closed(inner) for inner in exc.exceptions)
    return isinstance(exc, McpError) and exc.error.code == CONNECTION_CLOSED


def _boundary_interceptor(server: McpServer):
    """Map failures at this server's boundary onto what the graph's retry and fallback understand."""

    async def intercept(request: MCPToolCallRequest, handler):
        try:
            result = await handler(request)
        except Exception as exc:
            if _connection_closed(exc):
                raise TransientMcpError(
                    f"the {server.name} MCP server closed the connection before answering (it may have crashed)"
                ) from exc
            raise
        if not (isinstance(result, CallToolResult) and result.isError):
            return result
        text = _text(result)
        if server.login and _matches(server.login.error_patterns, text):
            login = server.login
            return CallToolResult(isError=True, content=[TextContent(type="text", text=(
                f"{text}\nNot logged in to {login.service}: this is permanent until the user logs in. "
                f"Tell the user to log in with `{login.command}` and restart the agent."
            ))])
        if _matches(server.transient_errors, text):
            raise TransientMcpError(text)
        return result  # any other tool error reaches the model as an error ToolMessage

    return intercept


async def _load_server(server: McpServer) -> list[BaseTool]:
    client = MultiServerMCPClient(
        {server.name: server.connection},
        tool_name_prefix=True,
        tool_interceptors=[_boundary_interceptor(server)],
    )
    tools = await client.get_tools(server_name=server.name)
    if server.login:
        await _check_login(client, server, server.login)
    hidden = {f"{server.name}_{name}" for name in server.hidden_tools}
    return classify_mcp_tools(
        [tool for tool in tools if tool.name not in hidden],
        read_allowlist={f"{server.name}_{name}" for name in server.read_allowlist},
        trust_read_only_hint=server.trust_read_only_hint,
    )


async def load_mcp_tools(servers: list[McpServer]) -> tuple[list[BaseTool], list[str]]:
    """Load every server's tools concurrently. Returns (tools, notices about unavailable servers)."""

    async def load(server: McpServer) -> tuple[list[BaseTool], str | None]:
        if server.connection is None:
            return [], f"{server.name} tools unavailable: {server.unavailable_reason}"
        try:
            return await _load_server(server), None
        except LoginRequired as exc:
            return [], f"{server.name} tools unavailable: {exc}"
        except Exception as exc:  # isolate: one broken server must not stop the others
            logger.warning("MCP server %s failed to start", server.name, exc_info=exc)
            while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
                exc = exc.exceptions[0]  # the cause, not "unhandled errors in a TaskGroup"
            return [], f"{server.name} tools unavailable: the server failed to start ({type(exc).__name__}: {exc})"

    results = await asyncio.gather(*(load(server) for server in servers))
    tools = [tool for server_tools, _ in results for tool in server_tools]
    notices = [notice for _, notice in results if notice]
    return tools, notices
