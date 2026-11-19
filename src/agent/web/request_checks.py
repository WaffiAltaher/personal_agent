"""
request_checks.py — ``Host`` and ``Origin`` checks on every request (ADR-018), as ASGI middleware.

Every request is refused (400) unless ``Host`` is one of the app's own hosts, which defeats DNS
rebinding. Every state-changing request (any method but GET, HEAD and OPTIONS) and every event
stream (``Accept: text/event-stream``) is refused (403) unless ``Origin`` is the app's own, so
another web page in the owner's browser can't act through the owner's session. No CORS headers
are ever sent.
"""

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RequestChecks:
    def __init__(self, app: ASGIApp, *, allowed_hosts: frozenset[str]):
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if host not in self.allowed_hosts:
            await PlainTextResponse("Invalid Host header.", status_code=400)(scope, receive, send)
            return
        is_event_stream = "text/event-stream" in headers.get("accept", "")
        if scope["method"] not in SAFE_METHODS or is_event_stream:
            if headers.get("origin") not in (f"http://{host}", f"https://{host}"):
                await PlainTextResponse("Missing or foreign Origin.", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
