"""
server.py — startup of ``python -m agent.web``: checks, then one graph served by uvicorn.

First the web-only checks (a password hash is set, the React app is built), then the CLI's
startup steps in the CLI's order and with its messages (``agent.startup``): build the model,
check Langfuse, check the Google and Claude Code logins, load tools with notices. What those
checks found is the first state of the login status strip (``startup_logins``). Real data only
(ADR-018): one checkpointer on the real checkpoint file and one compiled graph serve every
Conversation for the server's lifetime.
"""

from agent import startup
from agent.chat_model import ModelConfigError, create_chat_model, is_claude_code_model
from agent.config import settings
from agent.graph import build_graph, checkpoint_db, get_checkpointer
from agent.tools import load_all_tools, mcp_servers
from agent.tracing import flush_traces
from agent.web.app import WEB_DIST, WebConfig, create_app
from agent.web.logins import startup_logins

NO_PASSWORD = "no web password is set. Set one with: python -m agent.web.set_password"
BUILD_COMMAND = "cd web && npm install && npm run build"


def web_config() -> WebConfig:
    """The server's settings, or stop startup naming what is missing."""
    if not settings.web_password_hash:
        startup.cannot_start(NO_PASSWORD)
    if not (WEB_DIST / "index.html").exists():
        startup.cannot_start(f"the web app is not built ({WEB_DIST} is missing). Build it with: {BUILD_COMMAND}")
    return WebConfig(password_hash=settings.web_password_hash, port=settings.web_port,
                     host=settings.web_host, dist_dir=WEB_DIST)


async def run_uvicorn(app, web: WebConfig) -> None:
    import uvicorn

    print(f"Web interface on http://{web.host}:{web.port}")
    await uvicorn.Server(uvicorn.Config(app, host=web.host, port=web.port)).serve()


async def serve(*, run=run_uvicorn) -> None:
    web = web_config()
    try:
        model = create_chat_model()
    except ModelConfigError as exc:
        startup.cannot_start(exc)
    langfuse_connected = startup.check_langfuse()
    startup.check_logins()

    db_path = checkpoint_db(fixtures=False)
    try:
        async with get_checkpointer(db_path) as checkpointer:
            tools, notices = await load_all_tools(fixtures=False)
            startup.print_notices(notices)
            # As check_logins: Claude Code is on the strip when a claude_code: model is configured.
            claude_code = any(is_claude_code_model(m) for m in (settings.model_name, settings.eval_judge_model))
            logins = startup_logins(mcp_servers(fixtures=False), tools=tools, notices=notices,
                                    claude_code_binary=settings.claude_code_binary if claude_code else None)
            app = create_app(
                graph=build_graph(checkpointer, tools, model),
                tools=tools,
                model=model,
                checkpoint_path=db_path,
                web=web,
                langfuse_connected=langfuse_connected,
                logins=logins,
            )
            await run(app, web)
    finally:
        flush_traces()
