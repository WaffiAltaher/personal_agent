"""
The web server's login and request checks (ticket web-interface/02), through FastAPI's test client.

The app comes from `create_app` with an injected graph, tools and stand-in model (ADR-011): no
request here reaches a model, an MCP server or a real login.
"""

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from agent.web import WebConfig, create_app

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
PASSWORD = "correct horse battery staple"
# Cheap parameters keep the tests fast; verifying reads the parameters from the hash itself.
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


class Clock:
    """A clock the test moves by hand, for the login rate limit's window."""
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def web(tmp_path, scripted_model):
    """Factory: web(password_hash=...) -> (TestClient on 127.0.0.1:PORT, clock)."""
    from langgraph.checkpoint.memory import InMemorySaver

    from agent.graph import build_graph

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Agent</title><div id=root></div>")
    model = scripted_model([])
    graph = build_graph(InMemorySaver(), None, model)

    def make(password_hash=None, host="127.0.0.1"):
        clock = Clock()
        app = create_app(
            graph=graph, tools=[], model=model, checkpoint_path=str(tmp_path / "hitl.db"),
            web=WebConfig(password_hash=password_hash or FAST_HASHER.hash(PASSWORD), port=PORT,
                          host=host, dist_dir=dist),
            clock=clock,
        )
        return TestClient(app, base_url=f"http://127.0.0.1:{PORT}"), clock
    return make


def login(client, password=PASSWORD, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.post("/api/login", json={"password": password}, headers=headers)


def test_correct_password_sets_a_week_long_strict_httponly_session_cookie(web):
    client, _ = web()

    response = login(client)

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("session=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "SameSite=Strict" in cookie
    assert "Max-Age=604800" in cookie
    assert "Secure" not in cookie  # served on 127.0.0.1: a Secure cookie would never be sent back
    assert client.get("/api/session").status_code == 200


def test_the_cookie_is_secure_when_the_server_binds_beyond_localhost(web):
    client, _ = web(host="0.0.0.0")

    assert "Secure" in login(client).headers["set-cookie"]


def test_wrong_password_is_refused_without_a_cookie(web):
    client, _ = web()

    response = login(client, password="wrong")

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert client.get("/api/session").status_code == 401


def test_five_failed_logins_in_a_minute_refuse_even_the_right_password_until_the_window_passes(web):
    client, clock = web()
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401

    assert login(client).status_code == 429

    clock.now += 61
    assert login(client).status_code == 200


def test_a_session_ends_seven_days_after_login(web, monkeypatch):
    import time

    from itsdangerous.timed import TimestampSigner

    client, _ = web()
    login(client)
    logged_in_at = int(time.time())

    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: logged_in_at + 7 * 24 * 3600 - 60)
    assert client.get("/api/session").status_code == 200
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: logged_in_at + 7 * 24 * 3600 + 60)
    assert client.get("/api/session").status_code == 401


def test_a_new_password_ends_every_existing_session(web):
    old_client, _ = web()
    login(old_client)
    cookie = old_client.cookies["session"]

    new_client, _ = web(password_hash=FAST_HASHER.hash("a new password"))
    new_client.cookies.set("session", cookie)

    assert new_client.get("/api/session").status_code == 401


def test_logout_clears_the_cookie(web):
    client, _ = web()
    login(client)

    response = client.post("/api/logout", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/api/session").status_code == 401


def test_every_api_endpoint_except_login_refuses_a_request_without_a_session(web):
    client, _ = web()
    api_routes = [  # every route the app has, as its OpenAPI schema lists them (none is hidden)
        (method.upper(), path)
        for path, operations in client.app.openapi()["paths"].items()
        if path.startswith("/api/")
        for method in operations
    ]
    assert len(api_routes) >= 2  # logout and session at least: the check below must check something

    for method, path in api_routes:
        if path == "/api/login":
            continue
        response = client.request(method, path, headers={"Origin": ORIGIN})
        assert response.status_code == 401, (method, path)


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1:9999", "localhost", f"attacker.test:{PORT}"])
def test_a_wrong_host_is_refused_everywhere(web, host):
    client, _ = web()
    login(client)

    for method, path in [("GET", "/"), ("GET", "/api/session"), ("POST", "/api/login")]:
        response = client.request(method, path, headers={"Host": host, "Origin": ORIGIN},
                                  json={"password": PASSWORD})
        assert response.status_code == 400, (method, path)


def test_localhost_and_127_0_0_1_on_the_port_are_both_accepted(web):
    client, _ = web()

    for host in (f"localhost:{PORT}", f"127.0.0.1:{PORT}"):
        response = client.post("/api/login", json={"password": PASSWORD},
                               headers={"Host": host, "Origin": f"http://{host}"})
        assert response.status_code == 200, host


@pytest.mark.parametrize("origin", [None, "http://evil.example", f"http://localhost:{PORT + 1}", "null"])
def test_a_foreign_or_missing_origin_is_refused_on_state_changing_requests(web, origin):
    client, _ = web()
    assert login(client).status_code == 200

    assert login(client, origin=origin).status_code == 403
    headers = {"Origin": origin} if origin else {}
    assert client.post("/api/logout", headers=headers).status_code == 403
    assert client.get("/api/session").status_code == 200  # the refused logout did not log out


def test_a_foreign_or_missing_origin_is_refused_on_event_streams(web):
    client, _ = web()
    login(client)

    for headers in ({}, {"Origin": "http://evil.example"}):
        response = client.get("/api/session", headers={"Accept": "text/event-stream", **headers})
        assert response.status_code == 403
    assert client.get("/api/session", headers={"Accept": "text/event-stream", "Origin": ORIGIN}).status_code == 200


def test_plain_reads_need_no_origin(web):
    client, _ = web()
    login(client)

    assert client.get("/api/session").status_code == 200
    assert client.get("/").status_code == 200


def test_no_cors_headers_are_sent(web):
    client, _ = web()

    for response in (
        login(client, origin="http://evil.example"),
        client.options("/api/login", headers={"Origin": "http://evil.example",
                                              "Access-Control-Request-Method": "POST"}),
        login(client),
    ):
        assert not any(h.lower().startswith("access-control-") for h in response.headers), response.headers


def test_the_built_app_is_served_without_a_session(web):
    client, _ = web()

    response = client.get("/")

    assert response.status_code == 200
    assert "<div id=root>" in response.text
