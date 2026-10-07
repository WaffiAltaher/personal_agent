# tests/informer_server/test_limits.py
"""Informer allows 60 requests per minute and 5000 per day. The server stays under the
first by itself, honours the quota headers, and reports failures in a usable form.

Time is a fake clock shared by the server's limiter and the fake API: nothing sleeps."""

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
        is_error, text = await call_tool(session, "list_overdue_invoices", as_of="2026-10-07")

    assert is_error
    assert "daily" in text and "5000" in text
    assert "transient" not in text.lower()


@pytest.mark.asyncio
async def test_daily_quota_running_out_mid_call_is_the_same_error(fake_informer, connect, call_tool):
    fake_informer.daily_limit = 1  # the first page uses the last request of the day

    async with connect() as session:
        is_error, text = await call_tool(session, "list_overdue_invoices", as_of="2026-10-07")

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
