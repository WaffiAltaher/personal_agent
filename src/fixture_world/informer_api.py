# src/fixture_world/informer_api.py
"""A small local HTTP fake of Informer API v2, serving the seeded Fixture world.

Covers only the endpoints the Informer MCP server uses. Runs on 127.0.0.1 on a free port
in a background thread, so both an in-process server and a subprocess (stdio) server can
reach it through the base-URL override:

    with FakeInformerApi() as fake:
        ...  # point INFORMER_BASE_URL at fake.base_url
        fake.failure = Failure.UNAUTHORIZED  # every request now gets a 401

Every response carries Informer's quota headers (X-RateLimit-*, X-DailyLimit-*).
"""

import json
import re
import threading
import time
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

API_PREFIX = "/v2"
# Seeded Sales invoices' Due dates are written for `fixture_world.clock.SEED_TODAY`: run the
# server with INFORMER_TODAY at that date for a stable set of Overdue invoices (2265.30 EUR).
# A fake made with `shift` moves the invoices' dates by that much, so INFORMER_TODAY at
# SEED_TODAY + shift sees the same Overdue invoices (see fixture_world.clock.seed_shift).
SALES_INVOICE_DATE_FIELDS = ("invoice_date", "expiry_date", "payment_date", "last_reminder_date",
                             "last_edit", "created_at")


class Failure(Enum):
    """Switchable failure modes; `None` on the fake means serve normally."""

    UNAUTHORIZED = "unauthorized"
    QUOTA_EXHAUSTED = "quota_exhausted"  # the daily request limit is used up: 429
    THROTTLED = "throttled"  # the per-minute limit is hit, the day's quota is not: 429, transient
    SERVER_ERROR = "server_error"  # a transient upstream failure: 503


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


def _in_filter(invoice: dict, status: str | None) -> bool:
    """Informer's sales-invoice status filters, as far as the Fixture world needs them."""
    if not status:
        return True
    if status == "concept":
        return invoice["concept"] == "1"
    if status == "open":
        return invoice["concept"] == "0" and invoice["totals"]["open"] > 0
    return False  # collect, accruals, collection_fines, payment_plans: none seeded


def _shift_date(value: str | None, shift: timedelta) -> str | None:
    """Move an Informer date ("YYYY-mm-dd", optionally followed by a time) by `shift`."""
    if not value or not shift:
        return value
    return (date.fromisoformat(value[:10]) + shift).isoformat() + value[10:]


def _shift_invoice(invoice: dict, shift: timedelta) -> dict:
    return {**invoice, **{f: _shift_date(invoice.get(f), shift) for f in SALES_INVOICE_DATE_FIELDS if f in invoice}}


def _paginate(items: list, query: dict) -> tuple[list, dict] | None:
    """One page, numbered from 0, with `prev`/`next` as Informer sends them.

    None means this page is past the end: the real API then answers HTTP 400
    "No records found" rather than an empty page. Omitting `page` is page 0.
    """
    records = int(query.get("records", 20))
    page = int(query.get("page", 0))
    start = page * records
    if page < 0 or (start >= len(items) and not (page == 0 and len(items) == 0)):
        return None
    prev = None if page == 0 else page - 1
    nxt = page + 1 if start + records < len(items) else None
    return items[start:start + records], {"prev": prev, "next": nxt}


def _json_number(amount: float) -> int | float:
    """964 or 512.8, as Informer's column-balance report gives amounts."""
    return int(amount) if amount.is_integer() else amount


class FakeInformerApi:
    def __init__(self, api_key: str = "fixture-api-key", security_code: str = "fixture-security-code",
                 shift: timedelta = timedelta(0)):
        self.api_key = api_key
        self.security_code = security_code
        self.failure: Failure | None = None
        self.relations: list[dict] = load_seed("relations")
        self.sales_invoices: list[dict] = [_shift_invoice(i, shift) for i in load_seed("sales_invoices")]
        self.requests: list[tuple[str, dict]] = []  # (path, query) of every request received
        self.fail_after = 0  # serve this many requests normally before `failure` applies
        self.clock = time.monotonic  # replaceable, so rate-limit tests need not wait
        self.rate_limit = 60
        self.daily_limit = 5000
        self.daily_used = 0
        self._minute_hits: list[float] = []
        self._lock = threading.Lock()
        self.administration: dict = load_seed("administration")
        self.ledgers: list[dict] = load_seed("ledgers")
        self.ledger_movements: list[dict] = load_seed("ledger_movements")
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}{API_PREFIX}"

    # --- request handling: (status, body) for a GET --------------------------------

    def handle(self, path: str, query: dict, headers) -> tuple[int, dict]:
        self.requests.append((path, query))
        failure = self.failure if len(self.requests) > self.fail_after else None
        if failure is Failure.UNAUTHORIZED or not self._authorised(headers):
            return 401, {"error": ["Authentication failed"], "response_code": 401}
        if failure is Failure.QUOTA_EXHAUSTED:
            self.daily_used = self.daily_limit
        refused = self._spend_quota()
        if refused:
            return refused
        if failure is Failure.THROTTLED:
            return 429, {"error": ["Too many requests."], "response_code": 429}
        if failure is Failure.SERVER_ERROR:
            return 503, {"error": ["Service temporarily unavailable"], "response_code": 503}
        for pattern, route in self._routes():
            match = re.fullmatch(API_PREFIX + pattern, path)
            if match:
                return route(query, *match.groups())
        return 404, {"error": ["Resource niet gevonden."], "response_code": 404}

    def _authorised(self, headers) -> bool:
        return headers.get("Apikey") == self.api_key and headers.get("Securitycode") == self.security_code

    # --- rate limits: 60 requests per minute, 5000 per day -------------------------

    def spend(self, minute: int = 0, day: int = 0) -> None:
        """Use up quota as if another client of the same API key made requests just now."""
        self._minute_hits += [self.clock()] * minute
        self.daily_used += minute + day

    def _spend_quota(self) -> tuple[int, dict] | None:
        """Count this request against the limits, or refuse it with a 429."""
        now = self.clock()
        self._minute_hits = [t for t in self._minute_hits if now - t < 60]
        if self.daily_used >= self.daily_limit:
            return 429, {"error": ["Daily request limit reached."], "response_code": 429}
        if len(self._minute_hits) >= self.rate_limit:
            return 429, {"error": ["Too many requests."], "response_code": 429}
        self._minute_hits.append(now)
        self.daily_used += 1
        return None

    def quota_headers(self) -> dict[str, str]:
        now = self.clock()
        in_minute = sum(1 for t in self._minute_hits if now - t < 60)
        return {
            "X-RateLimit-Limit": str(self.rate_limit),
            "X-RateLimit-Remaining": str(max(0, self.rate_limit - in_minute)),
            "X-DailyLimit-Limit": str(self.daily_limit),
            "X-DailyLimit-Remaining": str(max(0, self.daily_limit - self.daily_used)),
        }

    def _routes(self):
        return [
            (r"/relations", self._list_relations),
            (r"/relations/(\d+)", self._get_relation),
            (r"/invoices/sales", self._list_sales_invoices),
            (r"/invoices/sales/(\d+)", self._get_sales_invoice),
            (r"/administration", self._get_administration),
            (r"/ledgers", self._list_ledgers),
            (r"/reports/column-balance", self._column_balance),
        ]

    def _list_relations(self, query: dict) -> tuple[int, dict]:
        search = query.get("search", "")
        found = [r for r in self.relations if not search or _matches(r, search)]
        paged = _paginate(found, query)
        if paged is None:
            return 400, {"error": ["No records found"], "response_code": 400}
        page, pagination = paged
        return 200, {"pagination": pagination, "relations": page}

    def _get_relation(self, query: dict, relation_id: str) -> tuple[int, dict]:
        for relation in self.relations:
            if relation["id"] == int(relation_id):
                return 200, {**relation, "freefields": []}
        return 404, {"error": ["Resource niet gevonden."], "response_code": 404}

    def _list_sales_invoices(self, query: dict) -> tuple[int, dict]:
        found = [i for i in self.sales_invoices if _in_filter(i, query.get("filter"))]
        if "relation_id" in query:
            found = [i for i in found if i["relation_id"] == int(query["relation_id"])]
        paged = _paginate(found, query)
        if paged is None:
            return 400, {"error": ["No records found"], "response_code": 400}
        page, pagination = paged
        return 200, {"pagination": pagination, "invoices": page}

    def _get_sales_invoice(self, query: dict, invoice_id: str) -> tuple[int, dict]:
        for invoice in self.sales_invoices:
            if invoice["id"] == int(invoice_id):
                return 200, invoice
        return 404, {"error": ["Resource niet gevonden."], "response_code": 404}
    def _get_administration(self, query: dict) -> tuple[int, dict]:
        return 200, self.administration

    def _list_ledgers(self, query: dict) -> tuple[int, list]:
        return 200, self.ledgers  # a plain array, unpaginated, as in Informer's spec

    def _column_balance(self, query: dict) -> tuple[int, dict]:
        """The column balance (proef- en saldibalans) of the seeded journal, shaped as
        live Informer returns it: one entry per ledger with an opening balance or movements
        in range, keyed by ledger id, amounts as JSON numbers. The opening balance is the
        year's (balance ledgers carry earlier years forward), whatever the period range."""
        required = ("year", "period_from", "period_to", "ledger_number_from", "ledger_number_to")
        # Real Informer also treats ledger_number_from=0 as missing (observed live, HTTP 422).
        missing = [name for name in required
                   if name not in query or (name == "ledger_number_from" and int(query[name]) == 0)]
        if missing:
            return 422, {"error": [f"{name} is verplicht." for name in missing], "response_code": 422}
        year, period_from, period_to, ledger_from, ledger_to = (int(query[name]) for name in required)

        # Summed in floats, as live Informer evidently does (it returns e.g. 1141.6600000000035).
        ledgers = {ledger["number"]: ledger for ledger in self.ledgers}
        opening: dict[str, float] = {}  # debit minus credit
        movements: dict[str, list[float]] = {}
        for m in self.ledger_movements:
            number = m["ledger_number"]
            if not ledger_from <= int(number) <= ledger_to:
                continue
            if m["year"] < year and ledgers[number]["type"] == "balance":
                opening[number] = opening.get(number, 0.0) + float(m["debit"]) - float(m["credit"])
            elif m["year"] == year:
                period = m["period"]
                ledger_type = ledgers[number]["type"]
                in_range = (
                    1 <= period <= period_to
                    if ledger_type == "balance"
                    else period_from <= period <= period_to
                )
                if in_range:
                    debit_credit = movements.setdefault(number, [0.0, 0.0])
                    debit_credit[0] += float(m["debit"])
                    debit_credit[1] += float(m["credit"])

        report = {}
        for number in sorted(set(opening) | set(movements)):
            start = opening.get(number, 0.0)
            debit, credit = movements.get(number, [0.0, 0.0])
            end = start + debit - credit
            ledger = ledgers[number]
            report[str(ledger["id"])] = {
                "results": {str(year): {
                    "opening_balance_debet": _json_number(max(start, 0.0)),
                    "opening_balance_credit": _json_number(max(-start, 0.0)),
                    "trial_balance_debet": _json_number(debit),
                    "trial_balance_credit": _json_number(credit),
                    "saldi_balance_debet": _json_number(max(end, 0.0)),
                    "saldi_balance_credit": _json_number(max(-end, 0.0)),
                }},
                "data": {"description": ledger["description"], "number": ledger["number"], "rgs_code": ledger["rgs"]},
            }
        return 200, {"column_balance": report or []}  # live Informer gives an empty list, not {}

    # --- lifecycle ------------------------------------------------------------------

    def start(self) -> "FakeInformerApi":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                with fake._lock:
                    status, body = fake.handle(url.path, query, self.headers)
                    quota_headers = fake.quota_headers()
                payload = json.dumps(body).encode()
                self.send_response(status)
                for name, value in quota_headers.items():
                    self.send_header(name, value)
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
