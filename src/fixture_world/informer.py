"""The Informer MCP server we authored, run over stdio against the Fixture world's fake Informer API.

    python -m fixture_world.informer

Starts the fake Informer API on a free local port inside this process, then runs the real
Informer MCP server (`informer_mcp`) pointed at it through the base-URL override. So the
agent's `--fixtures` mode needs no separately running fake: the adapters start a fresh
server process per tool call, and each brings its own fake. The fake serves only seeded,
read-only data, so nothing is lost between calls.

"Today" is the Fixture world's (`clock.today()`, pinned by FIXTURE_WORLD_TODAY), as the model
and the MS365 stand-in see it. Seeded Sales invoice dates are written for `clock.SEED_TODAY`,
so the fake moves them by whole weeks onto the current week, as the MS365 stand-in moves its
seeded week (`clock.seed_shift()`).

FIXTURE_WORLD_INFORMER_FAILURE=<mode> switches the fake into a failure mode for every request
(`informer_api.Failure` values: unauthorized, quota_exhausted, throttled, server_error).
"""

import os
import tempfile

from fixture_world import clock
from fixture_world.informer_api import FakeInformerApi, Failure
from fixture_world.purchase_handover import handover_from_environment
from informer_mcp.config import InformerSettings
from informer_mcp.server import create_server


FAILURE_ENV = "FIXTURE_WORLD_INFORMER_FAILURE"


def main() -> None:
    # Each process has a fake of its own, with its own 60/min limit: so the rate-limit budget
    # is this process's own too, not one shared with earlier fakes that used the same port.
    with FakeInformerApi(shift=clock.seed_shift()) as fake, tempfile.TemporaryDirectory() as budget:
        if mode := os.environ.get(FAILURE_ENV):
            fake.failure = Failure(mode)
        settings = InformerSettings(
            _env_file=None,
            api_key=fake.api_key,
            security_code=fake.security_code,
            base_url=fake.base_url,
            today=clock.today(),
            rate_limit_dir=budget,
        )
        create_server(settings, handover=handover_from_environment()).run("stdio")


if __name__ == "__main__":
    main()
