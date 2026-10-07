"""The Informer MCP server we authored, run over stdio against the Fixture world's fake Informer API.

    python -m fixture_world.informer

Starts the fake Informer API on a free local port inside this process, then runs the real
Informer MCP server (`informer_mcp`) pointed at it through the base-URL override. So the
agent's `--fixtures` mode needs no separately running fake: the adapters start a fresh
server process per tool call, and each brings its own fake. The fake serves only seeded,
read-only data, so nothing is lost between calls.

Seeded Due dates are fixed (written for `clock.SEED_TODAY`), so "today" for Overdue invoices
is today's weekday within the seeded week, matching how the MS365 stand-in moves its seeded
week onto the current one.

FIXTURE_WORLD_INFORMER_FAILURE=<mode> switches the fake into a failure mode for every request
(`informer_api.Failure` values: unauthorized, quota_exhausted, server_error).
"""

import os

from fixture_world import clock
from fixture_world.informer_api import FakeInformerApi, Failure
from informer_mcp.config import InformerSettings
from informer_mcp.server import create_server


FAILURE_ENV = "FIXTURE_WORLD_INFORMER_FAILURE"


def seeded_today():
    """Today, moved into the seeded week (SEED_TODAY when FIXTURE_WORLD_TODAY pins the seeded Wednesday)."""
    return clock.today() - clock.seed_shift()


def main() -> None:
    with FakeInformerApi() as fake:
        if mode := os.environ.get(FAILURE_ENV):
            fake.failure = Failure(mode)
        settings = InformerSettings(
            _env_file=None,
            api_key=fake.api_key,
            security_code=fake.security_code,
            base_url=fake.base_url,
            today=seeded_today(),
        )
        create_server(settings).run("stdio")


if __name__ == "__main__":
    main()
