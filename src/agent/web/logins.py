"""
logins.py — the web interface's login status strip (ADR-018, spec "Login status").

``Logins`` holds one ``Integration`` per login the agent depends on (Google, Claude Code when a
``claude_code:`` model is configured, MS365, Informer): alive or dead, and the command that logs
in again. The startup checks set the first state, so nothing is checked when the server starts.

At the start of every turn ``refresh_for_turn`` reruns the checks in the background, each under
``check_timeout_s``, and waits for them at most ``turn_wait_s``: a slow or hanging check leaves the
cached state and never holds a turn up for longer. One refresh runs at a time; a turn that starts
while one is still running waits on that one. Every change is passed to ``on_change`` (the server
publishes it as a ``login_status`` event).

An MCP server skipped at startup for its login is loaded again by its check once the login
passes: its tools go to ``on_tools`` (the server binds them for later turns), and from then on
its check is the server's own login check.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

from agent.auth.claude_code import (
    CLAUDE_CODE_LOGIN_COMMAND,
    ClaudeCodeLoginCheckTimeout,
    ClaudeCodeLoginRequired,
    check_claude_code_login,
)
from agent.auth.google import GOOGLE_LOGIN_COMMAND, GoogleLoginRequired, check_google_login
from agent.tools.mcp_loader import LoginNotice, LoginRequired, McpServer, check_mcp_login, load_mcp_server

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_S = 10.0
TURN_WAIT_S = 1.0
SETUP_COMMAND = "./scripts/setup_wizard.sh"

# A check returns why the login is dead, or None when it is alive.
Check = Callable[[], Awaitable[str | None]]


@dataclass
class Integration:
    name: str
    command: str  # the login command shown while it is dead
    check: Check | None  # None: the state is fixed for the server's lifetime
    alive: bool = True
    detail: str | None = None  # why it is dead

    def row(self) -> dict:
        return {"name": self.name, "alive": self.alive, "command": self.command, "detail": self.detail}


@dataclass
class Logins:
    integrations: list[Integration] = field(default_factory=list)
    check_timeout_s: float = CHECK_TIMEOUT_S
    turn_wait_s: float = TURN_WAIT_S
    on_change: Callable[[list[dict]], None] | None = None
    on_tools: Callable[[list[BaseTool]], None] | None = None
    _refresh: asyncio.Task | None = None

    def status(self) -> list[dict]:
        return [integration.row() for integration in self.integrations]

    async def refresh_for_turn(self) -> None:
        """Recheck every login, waiting at most ``turn_wait_s``; the checks finish in the background."""
        if not any(integration.check for integration in self.integrations):
            return
        if self._refresh is None or self._refresh.done():
            self._refresh = asyncio.create_task(self._refresh_all())
        await asyncio.wait({self._refresh}, timeout=self.turn_wait_s)

    async def _refresh_all(self) -> None:
        before = self.status()
        await asyncio.gather(*(self._recheck(i) for i in self.integrations if i.check))
        if self.status() != before and self.on_change:
            self.on_change(self.status())

    async def _recheck(self, integration: Integration) -> None:
        try:
            problem = await asyncio.wait_for(integration.check(), self.check_timeout_s)
        except TimeoutError:
            logger.warning("%s login check did not answer within %g s", integration.name, self.check_timeout_s)
            return  # keep the cached state
        except Exception as exc:
            problem = f"the login check failed ({type(exc).__name__}: {exc})"
        integration.alive, integration.detail = problem is None, problem

    def tools_loaded(self, tools: list[BaseTool]) -> None:
        if self.on_tools:
            self.on_tools(tools)


def google_login() -> Integration:
    """Google, alive as startup found it; its check reads the token file again."""
    async def check() -> str | None:
        try:
            await asyncio.to_thread(check_google_login)
        except (GoogleLoginRequired, FileNotFoundError) as exc:
            return str(exc)
        return None
    return Integration("Google", GOOGLE_LOGIN_COMMAND, check)


def claude_code_login(binary: str) -> Integration:
    """Claude Code, alive as startup found it; its check asks ``claude auth status`` again."""
    async def check() -> str | None:
        try:
            await asyncio.to_thread(check_claude_code_login, binary)
        except (ClaudeCodeLoginRequired, ClaudeCodeLoginCheckTimeout, FileNotFoundError) as exc:
            return str(exc)
        return None
    return Integration("Claude Code", CLAUDE_CODE_LOGIN_COMMAND, check)


def mcp_login(server: McpServer, *, loaded: bool, notice: str | None, logins: Logins) -> Integration:
    """An MCP server as startup left it. A server with a login check is rechecked; one skipped at
    startup for its login (a ``LoginNotice``) is loaded again when its login passes, and its tools
    go to ``logins.tools_loaded``. One skipped for another reason stays skipped."""
    command = server.login.command if server.login else SETUP_COMMAND
    integration = Integration(server.name, command, None, alive=loaded, detail=None if loaded else notice)
    if server.login is None or server.connection is None:
        return integration  # no login to recheck: loaded or not, it stays so
    if not loaded and not isinstance(notice, LoginNotice):
        return integration  # it failed to start for another reason: a new login won't bring it up

    async def check_loaded() -> str | None:
        return await check_mcp_login(server)

    async def load_skipped() -> str | None:
        try:
            tools = await load_mcp_server(server)
        except LoginRequired as exc:
            return str(exc)
        integration.check = check_loaded
        logins.tools_loaded(tools)
        return None

    integration.check = check_loaded if loaded else load_skipped
    return integration


def startup_logins(servers: list[McpServer], *, tools: list[BaseTool], notices: list[str],
                   claude_code_binary: str | None = None) -> Logins:
    """The strip as startup left it: Google and (with a binary) Claude Code passed their startup
    checks; an MCP server is alive if its tools loaded, else dead with its startup notice."""
    logins = Logins()
    logins.integrations.append(google_login())
    if claude_code_binary is not None:
        logins.integrations.append(claude_code_login(claude_code_binary))
    for server in servers:
        loaded = any(tool.name.startswith(f"{server.name}_") for tool in tools)
        notice = next((n for n in notices if n.startswith(f"{server.name} ")), None)
        logins.integrations.append(mcp_login(server, loaded=loaded, notice=notice, logins=logins))
    return logins
