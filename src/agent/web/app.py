"""
app.py — the FastAPI app of the web interface (ADR-018), built by ``create_app``.

The factory takes everything that touches data from outside (graph, tools, model, checkpoint
path), so ``python -m agent.web`` passes the real ones and tests pass the Fixture world and the
stand-in model. They are kept on ``app.state`` for the endpoints. Every endpoint under ``/api``
except login depends on ``require_session``; the built React app is served from ``web/dist``.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from agent.config import PROJECT_ROOT
from agent.web.auth import SESSION_COOKIE, SESSION_MAX_AGE_S, Auth, require_session
from agent.web.conversations import list_conversations, transcript
from agent.web.request_checks import RequestChecks

WEB_DIST = PROJECT_ROOT / "web" / "dist"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class WebConfig:
    """How the server is reached and who may log in."""
    password_hash: str
    port: int = 8000
    host: str = "127.0.0.1"  # the bind host
    dist_dir: Path = WEB_DIST

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """The ``Host`` values the app answers: its own address on its port."""
        return frozenset(f"{name}:{self.port}" for name in LOCAL_HOSTS)


class LoginRequest(BaseModel):
    password: str


def create_app(
    *,
    graph,
    tools: list[BaseTool],
    model: BaseChatModel,
    checkpoint_path: str,
    web: WebConfig,
    langfuse_connected: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """The web app on one compiled graph. ``clock`` times the login rate limit (tests move it)."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.graph = graph
    app.state.tools = tools
    app.state.model = model
    app.state.checkpoint_path = checkpoint_path
    app.state.web = web
    app.state.langfuse_connected = langfuse_connected
    # A Secure cookie is never sent back over plain http, which is how localhost is served.
    app.state.auth = Auth(web.password_hash, secure_cookie=web.host not in LOCAL_HOSTS, clock=clock)
    app.add_middleware(RequestChecks, allowed_hosts=web.allowed_hosts)

    public = APIRouter(prefix="/api")
    api = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

    @public.post("/login")
    def login(body: LoginRequest, request: Request, response: Response):
        auth: Auth = request.app.state.auth
        client = request.client.host if request.client else "unknown"
        if auth.rate_limit.blocked(client):
            return JSONResponse({"detail": "Too many failed logins. Try again in a minute."}, status_code=429)
        if not auth.password_matches(body.password):
            auth.rate_limit.record_failure(client)
            return JSONResponse({"detail": "Wrong password."}, status_code=401)
        response.set_cookie(
            SESSION_COOKIE, auth.new_session(), max_age=SESSION_MAX_AGE_S,
            httponly=True, samesite="strict", secure=auth.secure_cookie,
        )
        return {"ok": True}

    @api.post("/logout")
    def logout(request: Request, response: Response):
        auth: Auth = request.app.state.auth
        response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="strict", secure=auth.secure_cookie)
        return {"ok": True}

    @api.get("/session")
    def session():
        return {"ok": True}

    @api.get("/conversations")
    def conversations(request: Request):
        return list_conversations(request.app.state.checkpoint_path)

    @api.get("/conversations/{thread_id}")
    async def conversation(thread_id: str, request: Request):
        state = await request.app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", [])
        if not messages:
            return JSONResponse({"detail": "No such Conversation."}, status_code=404)
        return transcript(thread_id, messages, state.interrupts)

    app.include_router(public)
    app.include_router(api)
    # Mounted last: the API routes above win over a same-named file.
    app.mount("/", StaticFiles(directory=web.dist_dir, html=True), name="app")
    return app
