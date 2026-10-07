# src/agent/tools/mcp_loader.py
"""
One loader for every MCP server the agent uses (MS365, Informer, ...).

Each server is described by an McpServer and loaded through langchain-mcp-adapters
with its name as the tool prefix ("ms365_get-calendar-view"). Servers are optional
and isolated: one that isn't configured, or fails to start, is skipped with a notice
naming it and why, and the agent starts with the rest.

Each server's tools are classified (read or Write action, failing closed) here, at
load time, with that server's own trust settings.
"""

import asyncio
import logging
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from agent.tools.classification import classify_mcp_tools

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpServer:
    """How to reach one MCP server, and which of its tools the model may see."""

    name: str  # also the tool-name prefix: "<name>_<tool>"
    connection: Connection | None  # None when the server isn't configured
    unavailable_reason: str = ""  # why connection is None, shown to the user
    hidden_tools: frozenset[str] = frozenset()  # server tool names (unprefixed) never bound
    # When set, only these server tool names (unprefixed) are bound, whatever their annotations say.
    exposed_tools: frozenset[str] | None = None
    read_allowlist: frozenset[str] = frozenset()  # server tool names (unprefixed) classified read
    trust_read_only_hint: bool = False  # classify tools annotated readOnlyHint as read


async def _load_server(server: McpServer) -> list[BaseTool]:
    client = MultiServerMCPClient({server.name: server.connection}, tool_name_prefix=True)
    tools = await client.get_tools(server_name=server.name)
    hidden = {f"{server.name}_{name}" for name in server.hidden_tools}
    exposed = None if server.exposed_tools is None else {f"{server.name}_{name}" for name in server.exposed_tools}
    return classify_mcp_tools(
        [tool for tool in tools if tool.name not in hidden and (exposed is None or tool.name in exposed)],
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
        except Exception as exc:  # isolate: one broken server must not stop the others
            logger.warning("MCP server %s failed to start", server.name, exc_info=exc)
            return [], f"{server.name} tools unavailable: the server failed to start ({type(exc).__name__}: {exc})"

    results = await asyncio.gather(*(load(server) for server in servers))
    tools = [tool for server_tools, _ in results for tool in server_tools]
    notices = [notice for _, notice in results if notice]
    return tools, notices
