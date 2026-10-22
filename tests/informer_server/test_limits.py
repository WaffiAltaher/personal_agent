# tests/informer_server/test_limits.py
"""Informer allows 60 requests per minute and 5000 per day. The server stays under the
first by itself, honours the quota headers, and reports failures in a usable form.

Time is a fake clock shared by the server's limiter and the fake API: nothing sleeps."""

import subprocess
import sys

import pytest

from fixture_world.informer_api import Failure
from informer_mcp.client import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(fake_informer) -> FakeClock:
    clock = FakeClock()
    fake_informer.clock = clock
    return clock


@pytest.fixture
def limiter(clock) -> RateLimiter:
    return RateLimiter(clock=clock, sleep=clock.sleep)


@pytest.mark.asyncio
async def test_stays_at_or_under_60_requests_per_minute(fake_informer, connect, call_tool, clock, limiter):
    async with connect(rate_limiter=limiter) as session:
        results = [await call_tool(session, "get_sales_invoice", invoice_id=5001) for _ in range(61)]

    assert not any(is_error for is_error, _ in results)
    assert clock.sleeps == [60.0]  # the 61st request waited for the minute to pass
    assert len(fake_informer.requests) == 61


@pytest.mark.asyncio
async def test_honours_the_remaining_requests_header(fake_informer, connect, call_tool, clock, limiter):
    fake_informer.spend(minute=59)  # another client of the same API key used most of this minute

    async with connect(rate_limiter=limiter) as session:
        first = await call_tool(session, "get_sales_invoice", invoice_id=5001)  # the 60th: 0 remaining
        assert clock.sleeps == []
        second = await call_tool(session, "get_sales_invoice", invoice_id=5001)

    assert not first[0] and not second[0]
    assert clock.sleeps == [60.0]


@pytest.mark.asyncio
async def test_exhausted_daily_quota_is_a_clear_tool_error(fake_informer, connect, call_tool):
    fake_informer.failure = Failure.QUOTA_EXHAUSTED

    async with connect() as session:
        is_error, text = await call_tool(session, "list_sales_invoices", status="open")

    assert is_error
    assert "daily" in text and "5000" in text
    assert "transient" not in text.lower()


@pytest.mark.asyncio
async def test_daily_quota_running_out_mid_call_is_the_same_error(
        fake_informer, connect, call_tool, informer_settings):
    fake_informer.daily_limit = 1  # the first page uses the last request of the day
    settings = informer_settings.model_copy(update={"page_size": 1})

    async with connect(settings) as session:
        is_error, text = await call_tool(session, "list_sales_invoices", status="open")

    assert is_error
    assert "daily" in text


@pytest.mark.asyncio
async def test_server_error_is_reported_as_transient(fake_informer, connect, call_tool):
    fake_informer.failure = Failure.SERVER_ERROR

    async with connect() as session:
        is_error, text = await call_tool(session, "list_sales_invoices")

    assert is_error
    assert "HTTP 503" in text and "transient" in text.lower()


@pytest.mark.asyncio
async def test_unreachable_informer_is_reported_as_transient(informer_settings, connect, call_tool):
    settings = informer_settings.model_copy(update={"base_url": "http://127.0.0.1:9/v2"})  # nothing listens

    async with connect(settings) as session:
        is_error, text = await call_tool(session, "get_sales_invoice", invoice_id=5001)

    assert is_error
    assert "transient" in text.lower()


@pytest.mark.asyncio
async def test_transient_failure_on_a_later_page_fails_the_call_rather_than_returning_half(
        fake_informer, informer_settings, connect, call_tool):
    fake_informer.failure = Failure.SERVER_ERROR
    fake_informer.fail_after = 1  # the first page succeeds, the second gets the 503
    settings = informer_settings.model_copy(update={"page_size": 3})

    async with connect(settings) as session:
        is_error, text = await call_tool(session, "list_sales_invoices")

    assert is_error
    assert "HTTP 503" in text


# --- one budget per API key, across sessions and processes ---------------------------------
#
# The agent's MCP client starts a fresh Informer MCP server process for every tool call, so a
# per-process limiter never limits anything. The budget is shared state, keyed by API key.

@pytest.mark.asyncio
async def test_separate_sessions_share_one_budget_per_api_key(fake_informer, informer_settings, connect,
                                                             call_tool, clock):
    def limiter():  # what each server process builds for itself, on the shared fake clock
        return RateLimiter.for_key(informer_settings, clock=clock, sleep=clock.sleep)

    async with connect(rate_limiter=limiter()) as session:
        for _ in range(40):
            await call_tool(session, "get_sales_invoice", invoice_id=5001)
    async with connect(rate_limiter=limiter()) as session:
        results = [await call_tool(session, "get_sales_invoice", invoice_id=5001) for _ in range(21)]

    assert not any(is_error for is_error, _ in results)
    assert clock.sleeps == [60.0]  # the 61st request of the minute waited, though in another session


@pytest.mark.asyncio
async def test_another_api_key_has_its_own_budget(informer_settings, clock):
    other = informer_settings.model_copy(update={"api_key": "another-key"})
    ours, theirs = (RateLimiter.for_key(s, clock=clock, sleep=clock.sleep) for s in (informer_settings, other))

    for _ in range(60):
        await ours.acquire()
    await theirs.acquire()

    assert clock.sleeps == []


_ACQUIRE = """
import asyncio, sys
from informer_mcp.client import RateLimiter
from informer_mcp.config import InformerSettings

waits = []
async def sleep(seconds):
    waits.append(seconds)

settings = InformerSettings(_env_file=None, api_key="key", security_code="code", rate_limit_dir=sys.argv[1])
limiter = RateLimiter.for_key(settings, sleep=sleep)

async def main():
    for _ in range(int(sys.argv[2])):
        await limiter.acquire()

asyncio.run(main())
print(len(waits))
"""


def test_separate_processes_share_one_budget(tmp_path):
    def run(requests: int) -> int:
        out = subprocess.run([sys.executable, "-c", _ACQUIRE, str(tmp_path), str(requests)],
                             capture_output=True, text=True, check=True).stdout
        return int(out)

    assert run(60) == 0  # one process uses the minute's 60 requests
    assert run(1) == 1  # the next process's first request has to wait
