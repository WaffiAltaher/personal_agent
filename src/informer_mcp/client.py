# src/informer_mcp/client.py
"""Thin async HTTP client for Informer API v2."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

import httpx

from informer_mcp.config import InformerSettings

# Informer's limits per API key.
REQUESTS_PER_MINUTE = 60


class InformerError(Exception):
    """An Informer API failure, worded for the MCP client (and the model) to read."""


class InformerTransientError(InformerError, ConnectionError):
    """A failure worth retrying: Informer unreachable, timing out, 429 or 5xx.

    A ConnectionError, so the agent's retry policy treats it as transient in-process.
    Over MCP only the text travels: it starts with TRANSIENT_ERROR_PREFIX and names the
    HTTP status, so an MCP client can recognise it too.
    """


TRANSIENT_ERROR_PREFIX = "Transient Informer failure"


class RateLimiter:
    """Keeps requests at or under `limit` per `period` seconds (a sliding window), and
    pauses for a whole period when Informer says no requests remain this minute.
    The clock and sleep are injectable so tests need not wait."""

    def __init__(self, limit: int = REQUESTS_PER_MINUTE, period: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._limit = limit
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait, if needed, until one more request is allowed, and count it."""
        async with self._lock:
            now = self._clock()
            while self._sent and now - self._sent[0] >= self._period:
                self._sent.popleft()
            wait = self._blocked_until - now
            if len(self._sent) >= self._limit:
                wait = max(wait, self._sent[0] + self._period - now)
            if wait > 0:
                await self._sleep(wait)
            self._sent.append(self._clock())

    def observe(self, remaining: int | None) -> None:
        """Honour Informer's X-RateLimit-Remaining: at zero, pause for a whole period."""
        if remaining is not None and remaining <= 0:
            self._blocked_until = self._clock() + self._period


class InformerClient:
    def __init__(self, settings: InformerSettings, rate_limiter: RateLimiter | None = None):
        self._settings = settings
        self._limiter = rate_limiter or RateLimiter()

    async def get(self, path: str, params: dict | None = None) -> dict:
        headers = {
            "Apikey": self._settings.api_key,
            "Securitycode": self._settings.security_code,
            "Accept": "application/json",
        }
        await self._limiter.acquire()
        try:
            async with httpx.AsyncClient(base_url=self._settings.base_url, headers=headers, timeout=30) as http:
                response = await http.get(path, params=params)
        except httpx.TransportError as e:
            raise InformerTransientError(
                f"{TRANSIENT_ERROR_PREFIX}: could not reach Informer at {self._settings.base_url} "
                f"({type(e).__name__}: {e}). Retrying later may succeed."
            ) from e
        self._limiter.observe(_int_header(response, "X-RateLimit-Remaining"))
        if response.status_code == 429 and _int_header(response, "X-DailyLimit-Remaining") == 0:
            limit = response.headers.get("X-DailyLimit-Limit", "5000")
            raise InformerError(
                f"Informer's daily API quota ({limit} requests per day) is exhausted. "
                "It resets tomorrow; retrying today will not help."
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise InformerTransientError(
                f"{TRANSIENT_ERROR_PREFIX}: HTTP {response.status_code} for {path}: {_error_text(response)}. "
                "Retrying later may succeed."
            )
        if response.status_code == 401:
            raise InformerError(
                "Informer rejected the credentials (HTTP 401). "
                "Check the INFORMER_API_KEY and INFORMER_SECURITY_CODE settings "
                f"(and INFORMER_BASE_URL, currently {self._settings.base_url})."
            )
        if response.is_error:
            raise InformerError(f"Informer returned HTTP {response.status_code} for {path}: {_error_text(response)}")
        return response.json()

    async def get_pages(self, path: str, key: str, params: dict | None = None) -> "Paged":
        """Read every page of a list endpoint, up to the `max_pages` cap."""
        params = {**(params or {}), "records": self._settings.page_size}
        items: list[dict] = []
        page = total = 0
        while page < self._settings.max_pages:
            page += 1
            data = await self.get(path, {**params, "page": page})
            items += data[key]
            total = data["pagination"]["total"]
            if page >= data["pagination"]["pages"]:
                return Paged(items, total, truncated=False)
        return Paged(items, total, truncated=len(items) < total)


class Paged:
    """The records read from a list endpoint, and whether the page cap cut them short."""

    def __init__(self, items: list[dict], total: int, truncated: bool):
        self.items = items
        self.total = total
        self.truncated = truncated

    def notice(self, what: str) -> dict:
        """`truncated`, plus a notice for the model when it is not seeing everything."""
        if not self.truncated:
            return {"truncated": False}
        return {
            "truncated": True,
            "notice": f"Truncated: showing the first {len(self.items)} of {self.total} {what} "
                      "(page cap reached). Narrow the query to see the rest.",
        }


def _int_header(response: httpx.Response, name: str) -> int | None:
    try:
        return int(response.headers[name])
    except (KeyError, ValueError):
        return None


def _error_text(response: httpx.Response) -> str:
    try:
        error = response.json().get("error")
    except ValueError:
        return response.text
    return "; ".join(error) if isinstance(error, list) else str(error)
