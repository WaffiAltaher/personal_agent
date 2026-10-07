# src/fixture_world/informer_api.py
"""A small local HTTP fake of Informer API v2, serving the seeded Fixture world.

Covers only the endpoints the Informer MCP server uses. Runs on 127.0.0.1 on a free port
in a background thread, so both an in-process server and a subprocess (stdio) server can
reach it through the base-URL override:

    with FakeInformerApi() as fake:
        ...  # point INFORMER_BASE_URL at fake.base_url
        fake.failure = Failure.UNAUTHORIZED  # every request now gets a 401
"""

import json
import math
import re
import threading
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

API_PREFIX = "/v2"


class Failure(Enum):
    """Switchable failure modes; `None` on the fake means serve normally."""

    UNAUTHORIZED = "unauthorized"


def load_seed(name: str):
    """Load a seeded Fixture world file from `fixture_world/data/informer/`."""
    return json.loads((files("fixture_world") / "data" / "informer" / f"{name}.json").read_text())


def relation_name(relation: dict) -> str:
    if relation["relation_type"] == 0:
        return relation["company_name"]
    parts = (relation.get("firstname"), relation.get("surname_prefix"), relation.get("surname"))
    return " ".join(p for p in parts if p)


def _matches(relation: dict, search: str) -> bool:
    """Informer's search: relation number exactly when numeric, other fields partially."""
    if search.isdigit():
        return relation["relation_number"] == int(search)
    fields = (relation_name(relation), relation.get("city"), relation.get("email"),
              relation.get("zip"), relation.get("street"), relation.get("coc"))
    return any(search.lower() in f.lower() for f in fields if f)


def _paginate(items: list, query: dict) -> tuple[list, dict]:
    page = int(query.get("page", 1))
    records = int(query.get("records", 20))
    start = (page - 1) * records
    pagination = {"page": page, "records": records, "total": len(items),
                  "pages": math.ceil(len(items) / records)}
    return items[start:start + records], pagination


class FakeInformerApi:
    def __init__(self, api_key: str = "fixture-api-key", security_code: str = "fixture-security-code"):
        self.api_key = api_key
        self.security_code = security_code
        self.failure: Failure | None = None
        self.relations: list[dict] = load_seed("relations")
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}{API_PREFIX}"

    # --- request handling: (status, body) for a GET --------------------------------

    def handle(self, path: str, query: dict, headers) -> tuple[int, dict]:
        if self.failure is Failure.UNAUTHORIZED or not self._authorised(headers):
            return 401, {"error": ["Authentication failed"], "response_code": 401}
        for pattern, route in self._routes():
            match = re.fullmatch(API_PREFIX + pattern, path)
            if match:
                return route(query, *match.groups())
        return 404, {"error": ["Resource niet gevonden."], "response_code": 404}

    def _authorised(self, headers) -> bool:
        return headers.get("Apikey") == self.api_key and headers.get("Securitycode") == self.security_code

    def _routes(self):
        return [
            (r"/relations", self._list_relations),
            (r"/relations/(\d+)", self._get_relation),
        ]

    def _list_relations(self, query: dict) -> tuple[int, dict]:
        search = query.get("search", "")
        found = [r for r in self.relations if not search or _matches(r, search)]
        page, pagination = _paginate(found, query)
        return 200, {"pagination": pagination, "relations": page}

    def _get_relation(self, query: dict, relation_id: str) -> tuple[int, dict]:
        for relation in self.relations:
            if relation["id"] == int(relation_id):
                return 200, {**relation, "freefields": []}
        return 404, {"error": ["Resource niet gevonden."], "response_code": 404}

    # --- lifecycle ------------------------------------------------------------------

    def start(self) -> "FakeInformerApi":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                status, body = fake.handle(url.path, query, self.headers)
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # keep test output quiet
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, args=(0.05,), daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def __enter__(self) -> "FakeInformerApi":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
