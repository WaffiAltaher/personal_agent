# src/agent/tools/mcp_environment.py
"""What an MCP server process may see of the agent's environment: an allowlist, never all of it.

Every server runs as a child process of the agent. Third-party code (npx, the MS365 server)
would otherwise see every API key in the shell and the .env. Each server gets the system
basics below plus its own settings, and nothing else. A server that fails to start because
it needs one more variable gets that variable added here, with a comment saying why.
"""

import os
from collections.abc import Iterable

# System basics: what Node, npx and Python need to run, find their caches and reach the network.
SYSTEM_VARIABLES = frozenset({
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",  # with USER, identifies the account to the macOS keychain
    "SHELL",
    "TERM",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    # Node and npm on machines behind a proxy or a corporate certificate authority.
    "NODE_OPTIONS",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
})

# The Fixture world's own settings (its clock, failure switches and draft log), for its stand-ins.
FIXTURE_PREFIX = "FIXTURE_WORLD_"


def inherited(names: Iterable[str]) -> dict[str, str]:
    """The agent's current value of each named variable that is set."""
    return {name: os.environ[name] for name in names if name in os.environ}


def system_environment() -> dict[str, str]:
    """The system basics, as the agent's process has them."""
    return inherited(SYSTEM_VARIABLES)


def fixture_environment() -> dict[str, str]:
    """The system basics plus the Fixture world's own settings, and nothing else."""
    fixture = {key: value for key, value in os.environ.items() if key.startswith(FIXTURE_PREFIX)}
    return {**system_environment(), **fixture}
