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

Purchase invoices are e-mailed with the real e-mail transport (ADR-019), from INVOICE_MAILBOX to
INCOMING_ADDRESS, through the MS365 stand-in (`python -m fixture_world.ms365`) started per upload
with the real server's arguments. The stand-in records what it sent in the file named by
FIXTURE_WORLD_MS365_SENT, and FIXTURE_WORLD_MS365_SEND_FAILURE=transient fails the send.

The Purchase invoice upload log is a file, since each tool call is a new process:
FIXTURE_WORLD_INFORMER_UPLOAD_LOG names it (default: one stable file in the temp dir).
FIXTURE_WORLD_INFORMER_DOWNLOADS_DIR names the folder PDFs may be uploaded from (default: ~/Downloads).
Only FIXTURE_WORLD_* variables reach this process (see agent.tools.mcp_environment), so these
are the names to use, not INFORMER_*.

FIXTURE_WORLD_INFORMER_FAILURE=<mode> switches the fake into a failure mode for every request
(`informer_api.Failure` values: unauthorized, quota_exhausted, throttled, server_error).
"""

import os
import sys
import tempfile
from pathlib import Path

from mcp import StdioServerParameters

from fixture_world import clock, ms365
from fixture_world.informer_api import FakeInformerApi, Failure
from informer_mcp.config import InformerSettings
from informer_mcp.email_handover import SERVER_ARGS, EmailHandover, login_command, stdio_connection
from informer_mcp.server import create_server


FAILURE_ENV = "FIXTURE_WORLD_INFORMER_FAILURE"
UPLOAD_LOG_ENV = "FIXTURE_WORLD_INFORMER_UPLOAD_LOG"  # JSON Lines file: the Purchase invoice upload log
DOWNLOADS_ENV = "FIXTURE_WORLD_INFORMER_DOWNLOADS_DIR"  # the folder Purchase invoice PDFs may come from
DEFAULT_UPLOAD_LOG = Path(tempfile.gettempdir()) / "fixture_world_informer_purchase_uploads.jsonl"

# Made up: the Fixture world's Invoice mailbox and Informer incoming address.
INVOICE_MAILBOX = "invoices@ittopia.example"
INCOMING_ADDRESS = "purchase-7f3k@incoming.informer.example"

# What the MS365 stand-in reads when it sends: its clock, sent log and failure switches.
STAND_IN_VARIABLES = (clock.TODAY_ENV, ms365.SENT_ENV, ms365.SEND_FAILURE_ENV, ms365.FAILURE_ENV,
                      ms365.FAILURE_FILE_ENV)


def upload_log_path() -> Path:
    """The upload log, a file that outlives this process (each tool call starts a new one). The
    same stable file unless FIXTURE_WORLD_INFORMER_UPLOAD_LOG names another; evals name one per run."""
    return Path(os.environ.get(UPLOAD_LOG_ENV) or DEFAULT_UPLOAD_LOG)


def ms365_stand_in_parameters() -> StdioServerParameters:
    """The MS365 stand-in, started as the real server is (the same arguments, outside the repo)."""
    # This process sees the system basics and FIXTURE_WORLD_* (and INFORMER_DOWNLOADS_DIR); the
    # stand-in gets the basics and only the Fixture world variables it reads.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("FIXTURE_WORLD_", "INFORMER_"))}
    env |= {name: os.environ[name] for name in STAND_IN_VARIABLES if name in os.environ}
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "fixture_world.ms365", *SERVER_ARGS],
        env=env,
        cwd=tempfile.gettempdir(),
    )


def main() -> None:
    # Each process has a fake of its own, with its own 60/min limit: so the rate-limit budget
    # is this process's own too, not one shared with earlier fakes that used the same port.
    with FakeInformerApi(shift=clock.seed_shift()) as fake, tempfile.TemporaryDirectory() as budget:
        if mode := os.environ.get(FAILURE_ENV):
            fake.failure = Failure(mode)
        extra = {}
        if downloads := os.environ.get(DOWNLOADS_ENV):  # pass only when set, or INFORMER_DOWNLOADS_DIR is ignored
            extra["downloads_dir"] = Path(downloads)
        settings = InformerSettings(
            _env_file=None,
            api_key=fake.api_key,
            security_code=fake.security_code,
            base_url=fake.base_url,
            today=clock.today(),
            rate_limit_dir=budget,
            purchase_upload_log=upload_log_path(),
            **extra,
        )
        handover = EmailHandover(
            stdio_connection(ms365_stand_in_parameters()),
            invoice_mailbox=INVOICE_MAILBOX,
            incoming_address=INCOMING_ADDRESS,
            login_command=login_command("@softeria/ms-365-mcp-server"),
        )
        create_server(settings, handover=handover).run("stdio")


if __name__ == "__main__":
    main()
