"""The web interface beside the CLI (ADR-018): ``python -m agent.web``."""

from agent.web.app import WebConfig, create_app
from agent.web.auth import require_session

__all__ = ["WebConfig", "create_app", "require_session"]
