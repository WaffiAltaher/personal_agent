# src/informer_mcp/config.py
from datetime import date

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
    # "Today" for Overdue invoices; unset means the current date in Amsterdam. Pin it to
    # run against the Fixture world, whose seeded Due dates are fixed.
    today: date | None = None

    model_config = SettingsConfigDict(
        env_prefix="INFORMER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
