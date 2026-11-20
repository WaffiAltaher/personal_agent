# src/agent/tools/mcp_loader.py
"""
One loader for every MCP server the agent uses (MS365, Informer, ...).

Each server is described by an McpServer and loaded through langchain-mcp-adapters
with its name as the tool prefix ("ms365_get-calendar-view"). Servers are optional
and isolated: one that isn't configured, or fails to start, is skipped with a notice
naming it and why, and the agent starts with the rest.

Each server's tools are classified (read or Write action, failing closed) here, at
load time, with that server's own trust settings. A server's ToolWrappers are bound
as Write actions in place of the server tools they replace, which are never bound.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_mcp_adapters.sessions import Connection
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from agent.tools.classification import classify_mcp_tools, write_action

logger = logging.getLogger(__name__)


class TransientMcpError(Exception):
    """A transient failure at the MCP boundary; the graph's retry policy retries it on read tools."""


class LoginRequired(Exception):
    """The server's login is missing or expired."""


class LoginNotice(str):
    """A notice from ``load_mcp_tools`` that a server was skipped for its login (not for another failure)."""


@dataclass(frozen=True)
class LoginCheck:
    """How to tell that a server's login is missing or expired, and how the user logs in."""

    service: str  # what the user logs in to, e.g. "Microsoft 365"
    command: str  # the login command shown to the user
    check_tool: str  # server tool (unprefixed, need not be exposed) called at startup: an error or {"success": false} ⇒ not logged in
    error_patterns: tuple[str, ...] = ()  # regexes: a tool error matching one means the login is missing or expired


@dataclass(frozen=True)
class ToolWrapper:
    """An agent-side Write action over server tools, bound in place of a server tool the model never sees."""

    name: str  # unprefixed; bound as "<server>_<name>"
    replaces: str  # server tool name (unprefixed): never bound, whatever exposed_tools says
    # Builds the tool from its bound name and every tool the server lists (unprefixed names, exposed or not).
    build: Callable[[str, Mapping[str, BaseTool]], BaseTool]


@dataclass(frozen=True)
class McpServer:
    """How to reach one MCP server, and which of its tools the model may see."""

    name: str  # also the tool-name prefix: "<name>_<tool>"
    connection: Connection | None  # None when the server isn't configured
    unavailable_reason: str = ""  # why connection is None, shown to the user
    # When set, only these server tool names (unprefixed) are bound, whatever their annotations say.
    exposed_tools: frozenset[str] | None = None
    read_allowlist: frozenset[str] = frozenset()  # server tool names (unprefixed) classified read
    login: LoginCheck | None = None  # checked at startup; None when the server needs no login
    transient_errors: tuple[str, ...] = ()  # regexes: a tool error matching one is transient (retryable)
    wrappers: tuple[ToolWrapper, ...] = ()  # bound in place of the server tools they replace


def _text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def _login_problem(session: ClientSession, login: LoginCheck) -> str | None:
    """The reason the login is missing or expired, or None when it is fine."""
    result = await session.call_tool(login.check_tool, {})
    text = _text(result)
    try:
        status = json.loads(text)
    except ValueError:
        status = None
    if result.isError or (isinstance(status, dict) and status.get("success") is False):
        detail = status.get("message") or status.get("error") if isinstance(status, dict) else text
        return (f"not logged in to {login.service} ({detail}). "
                f"Log in with `{login.command}`, then restart the agent.")
    return None


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


async def _list_tools(session: ClientSession) -> list[MCPTool]:
    """Every tool the server lists, across all pages."""
    listed: list[MCPTool] = []
    cursor = None
    while True:
        page = await session.list_tools(cursor)
        listed.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            return listed


async def load_mcp_server(server: McpServer) -> list[BaseTool]:
    """One configured server's classified tools, as at startup. Raises LoginRequired when its login
    is missing or expired, or the server's own failure when it fails to start."""
    client = MultiServerMCPClient({server.name: server.connection})
    # One session serves both the tool listing and the login check, so the server starts once.
    # Each tool opens its own session per call (as the adapter's tools do), so they outlive this one.
    login_problem = None
    async with client.session(server.name) as session:
        listed = await _list_tools(session)
        if server.login:
            if any(tool.name == server.login.check_tool for tool in listed):
                login_problem = await _login_problem(session, server.login)
            else:  # can't check; tool errors will still name the login command (LoginCheck.error_patterns)
                logger.warning("MCP server %s has no %s tool; login not checked at startup",
                               server.name, server.login.check_tool)
    if login_problem:  # raised after the session closes, so it isn't wrapped in the session's task group
        raise LoginRequired(login_problem)
    interceptors = [_boundary_interceptor(server)]
    tools = [
        convert_mcp_tool_to_langchain_tool(
            None,
            tool,
            connection=server.connection,
            tool_interceptors=interceptors,
            server_name=server.name,
            tool_name_prefix=True,
        )
        for tool in listed
    ]
    exposed = None if server.exposed_tools is None else {f"{server.name}_{name}" for name in server.exposed_tools}
    replaced = {f"{server.name}_{wrapper.replaces}" for wrapper in server.wrappers}
    classified = classify_mcp_tools(
        [tool for tool in tools if (exposed is None or tool.name in exposed) and tool.name not in replaced],
        read_allowlist={f"{server.name}_{name}" for name in server.read_allowlist},
    )
    by_name = {tool.name.removeprefix(f"{server.name}_"): tool for tool in tools}
    for wrapper in server.wrappers:
        if wrapper.replaces not in by_name:
            logger.warning("MCP server %s has no %s tool; %s not bound", server.name, wrapper.replaces, wrapper.name)
            continue
        classified.append(write_action(wrapper.build(f"{server.name}_{wrapper.name}", by_name)))
    return classified


async def check_mcp_login(server: McpServer) -> str | None:
    """Why a configured server's login is missing or expired, or None when it is fine (or it has no
    login, or no check tool to ask)."""
    if server.login is None:
        return None
    async with MultiServerMCPClient({server.name: server.connection}).session(server.name) as session:
        if not any(tool.name == server.login.check_tool for tool in await _list_tools(session)):
            return None
        return await _login_problem(session, server.login)


async def load_mcp_tools(servers: list[McpServer]) -> tuple[list[BaseTool], list[str]]:
    """Load every server's tools concurrently. Returns (tools, notices about unavailable servers)."""

    async def load(server: McpServer) -> tuple[list[BaseTool], str | None]:
        if server.connection is None:
            return [], f"{server.name} tools unavailable: {server.unavailable_reason}"
        try:
            return await load_mcp_server(server), None
        except LoginRequired as exc:
            return [], LoginNotice(f"{server.name} tools unavailable: {exc}")
        except Exception as exc:  # isolate: one broken server must not stop the others
            logger.warning("MCP server %s failed to start", server.name, exc_info=exc)
            while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
                exc = exc.exceptions[0]  # the cause, not "unhandled errors in a TaskGroup"
            return [], f"{server.name} tools unavailable: the server failed to start ({type(exc).__name__}: {exc})"

    results = await asyncio.gather(*(load(server) for server in servers))
    tools = [tool for server_tools, _ in results for tool in server_tools]
    notices = [notice for _, notice in results if notice]
    return tools, notices
