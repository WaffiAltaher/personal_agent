# src/informer_mcp/config.py
from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo's `.env`, wherever the server is started from (the agent starts it in its own working directory).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

INFORMER_API_URL = "https://api.informer.eu/v2"


class InformerSettings(BaseSettings):
    """Read from INFORMER_* environment variables (or `.env`)."""

    api_key: str
    security_code: str
    # Override to point the server elsewhere, e.g. at the Fixture world's fake Informer API.
    base_url: str = INFORMER_API_URL
    # Paging: records per request, and the most pages one tool call reads before it
    # stops and says the result is truncated.
    page_size: int = 100
    max_pages: int = 10
    # Optional pinned "today" (Amsterdam); the Fixture world sets this from its clock.
    today: date | None = None
    # Where the rate-limit budget per API key is kept, shared by every server process using
    # the key (the agent starts one per tool call). Unset means a folder in the temp dir.
    rate_limit_dir: Path | None = None
    # Purchase invoice upload: only paths under this folder (default ~/Downloads).
    downloads_dir: Path | None = None
    # Maximum Purchase invoice PDF size in bytes (default 2 MB).
    purchase_upload_max_bytes: int = 2 * 1024 * 1024
    # Ledger numbers for financial tools (ticket 03 defaults; comma-separated).
    revenue_ledger_numbers: str = "8000"
    vat_charged_ledger_numbers: str = "1500,1542"
    vat_paid_ledger_numbers: str = "1520,1543"
    vat_closing_target_ledger: int = 1551
    # The upload log: one JSON line (content fingerprint, date) per successful hand-over, so a
    # repeat of the same contents is noticed. Every server process shares it, so it is a file.
    # Unset means ~/.informer_mcp/purchase-uploads.jsonl.
    purchase_upload_log: Path | None = None
    # Purchase invoice hand-over by e-mail (ADR-019): from the Invoice mailbox to the Informer
    # incoming address, both set in `.env` only, through the MS365 server package (pinned by the
    # agent) logged in as the owner. The upload tools exist only when all but the username are set.
    incoming_address: str | None = None
    invoice_mailbox: str | None = None
    ms365_package: str | None = None
    ms365_client_id: str | None = None
    ms365_tenant_id: str | None = None
    ms365_expected_username: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="INFORMER_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )
