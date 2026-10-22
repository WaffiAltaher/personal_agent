from agent.config import Settings
from agent.tools.ms365_mcp import ms365_server

# Red on purpose: it fails on the real code. The existing test deletes MS365_MCP_USE_KEYTAR
# from the environment before checking that it isn't passed on, so it can't fail.


def test_a_keytar_opt_out_in_the_shell_never_reaches_the_server(monkeypatch):
    monkeypatch.setenv("MS365_MCP_USE_KEYTAR", "false")  # e.g. left over in the shell profile
    settings = Settings(_env_file=None, ms365_mcp_client_id="client", ms365_mcp_tenant_id="tenant")

    env = ms365_server(settings).connection["env"]

    assert "MS365_MCP_USE_KEYTAR" not in env  # the token cache key stays in the macOS keychain
