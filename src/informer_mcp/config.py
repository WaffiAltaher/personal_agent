# src/informer_mcp/config.py
from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    model_config = SettingsConfigDict(
        env_prefix="INFORMER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
