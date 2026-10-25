"""
The default model is `claude_code:`, so anything in the suite that builds the configured model
or runs the real-mode startup checks would call the Claude Code CLI. The suite must never reach
the real `claude` (it spends the owner's subscription): outside `live` tests, CLAUDE_CODE_BINARY
names a binary that doesn't exist, so such a call fails loudly instead.
"""

import shutil

from agent.config import Settings, settings


def test_the_configured_claude_code_binary_cannot_be_found():
    assert shutil.which(settings.claude_code_binary) is None
    assert shutil.which(Settings().claude_code_binary) is None
