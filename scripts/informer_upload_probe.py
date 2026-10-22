#!/usr/bin/env python3
"""Send one Purchase invoice file to Informer's v1 create endpoint.

Usage, from the repo root:

    python scripts/informer_upload_probe.py --confirm path/to/invoice.pdf
    python scripts/informer_upload_probe.py --confirm --as-is path/to/invoice.jpg

Every run that passes --confirm creates a real purchase-invoice record in
the Informer administration. Without --confirm the script sends nothing.
The file's type is taken from its bytes, not its name. A PDF is sent as-is.
A JPEG or PNG is sent only with --as-is, so a probe of whether v1 accepts
images is deliberate. Anything else is refused. The JSON body is only
{"pdf": "<base64 of the file>"}; no invoice details are sent.

Credentials come from INFORMER_API_KEY and INFORMER_SECURITY_CODE. The v1
address is INFORMER_BASE_URL with the trailing /v2 replaced by /v1
(default https://api.informer.eu/v2). The printed request masks those
credentials and elides the file. Exit 0 means a response was printed,
including an error response.

This script is not part of the test suite. Do not import it from a test,
and do not run it except by hand. If the project virtualenv is not already
active, the script restarts itself with it.
"""


def _ensure_project_interpreter() -> None:
    """Re-run under the project virtualenv when started with another Python.

    `.venv/bin/python` is a symlink to the same interpreter `python` runs, so
    the environment is `sys.prefix`, not the resolved binary. Without this,
    `python scripts/informer_upload_probe.py` fails to import httpx.
    """
    import os
    import sys
    from pathlib import Path

    if os.environ.get("INFORMER_PROBE_PYTHON") == "1":
        return
    root = Path(__file__).resolve().parent.parent
    venv_python = root / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return
    if Path(sys.prefix).resolve() == (root / ".venv").resolve():
        return
    os.environ["INFORMER_PROBE_PYTHON"] = "1"
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


_ensure_project_interpreter()

import argparse
import base64
import json
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from informer_mcp.config import InformerSettings

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRET_HEADERS = {"apikey", "securitycode", "authorization", "proxy-authorization"}
IMAGE_KINDS = {"jpeg", "png"}


def file_kind(data: bytes) -> str | None:
    """The type the bytes actually are: pdf, jpeg, png, or None."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def v1_purchase_invoice_url(base_url: str) -> str:
    """v1 POST /invoice/purchase/ from a v2 base address. Refuses to guess otherwise."""
    base = base_url.strip().rstrip("/")
    if not base.endswith("/v2"):
        raise ValueError(
            f"Refusing to guess the v1 address from INFORMER_BASE_URL {base_url!r}. "
            "It must end in /v2 (the default is https://api.informer.eu/v2)."
        )
    return base[: -len("v2")] + "v1/invoice/purchase/"


def load_settings() -> InformerSettings:
    return InformerSettings(_env_file=REPO_ROOT / ".env")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send one Purchase invoice file to Informer v1. "
            "Every confirmed run creates a real record in the administration."
        ),
    )
    parser.add_argument("path", help="Path to the local file")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Confirm creating a real purchase-invoice record.",
    )
    parser.add_argument(
        "--as-is",
        action="store_true",
        help="Send JPEG or PNG content unchanged in the pdf field.",
    )
    return parser.parse_args(argv)


def header_lines(headers: httpx.Headers, secrets: set[str]) -> list[str]:
    """Header lines as sent or received. Credential values are masked."""
    lines = []
    for raw_name, raw_value in headers.raw:
        name = raw_name.decode("ascii", errors="replace")
        value = raw_value.decode("latin-1")
        if name.lower() in SECRET_HEADERS or value in secrets:
            value = "***"
        lines.append(f"{name}: {value}")
    return lines


def print_request(request: httpx.Request, pdf_note: str, secrets: set[str]) -> None:
    print("Request")
    print(f"{request.method} {request.url}")
    print("\n".join(header_lines(request.headers, secrets)))
    print()
    # The pdf value is replaced only here. Content-Length is the body that was sent.
    print(json.dumps({"pdf": pdf_note}, separators=(",", ":")))
    print()


def print_response(response: httpx.Response, secrets: set[str]) -> None:
    print("Response")
    reason = f" {response.reason_phrase}" if response.reason_phrase else ""
    print(f"HTTP {response.status_code}{reason}")
    print("\n".join(header_lines(response.headers, secrets)))
    print()
    print(response.content.decode("utf-8", errors="replace"))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm:
        print(
            "Refusing to run without --confirm. "
            "Every run creates a real purchase-invoice record. Nothing was sent.",
            file=sys.stderr,
        )
        return 2

    path = Path(args.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"Could not read {path}: {exc}", file=sys.stderr)
        return 2

    kind = file_kind(data)
    if kind is None:
        print(
            f"Refusing {path}: content is not a PDF, JPEG, or PNG ({len(data)} bytes). "
            "The type is taken from the bytes, not the file name. Nothing was sent.",
            file=sys.stderr,
        )
        return 2
    if kind in IMAGE_KINDS and not args.as_is:
        print(
            f"Refusing {path}: content is a {kind}. "
            "Pass --as-is to send the image unchanged in the pdf field. Nothing was sent.",
            file=sys.stderr,
        )
        return 2

    try:
        settings = load_settings()
    except ValidationError as exc:
        print(f"Informer settings are missing or invalid:\n{exc}", file=sys.stderr)
        return 2
    try:
        url = v1_purchase_invoice_url(settings.base_url)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    encoded = base64.b64encode(data).decode("ascii")
    sent = json.dumps({"pdf": encoded}, separators=(",", ":")).encode("ascii")
    pdf_note = f"<elided {len(data)} bytes, {len(encoded)} base64 characters, content {kind}>"
    secrets = {settings.api_key, settings.security_code}

    print("File")
    print(f"path: {path.resolve()}")
    print(f"content: {kind}")
    print(f"size: {len(data)} bytes")
    if kind in IMAGE_KINDS:
        print("image: sent as-is")
    print()

    headers = {
        "Apikey": settings.api_key,
        "Securitycode": settings.security_code,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        # One request only: a redirect must not turn into a second POST.
        with httpx.Client(timeout=60.0, follow_redirects=False) as client:
            request = client.build_request("POST", url, headers=headers, content=sent)
            print_request(request, pdf_note, secrets)
            response = client.send(request)
    except httpx.RequestError as exc:
        print(f"No response: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print_response(response, secrets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
