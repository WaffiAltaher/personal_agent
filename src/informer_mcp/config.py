# src/informer_mcp/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

INFORMER_API_URL = "https://api.informer.eu/v2"


class InformerSettings(BaseSettings):
    """Read from INFORMER_* environment variables (or `.env`)."""

    api_key: str
    security_code: str
    # Override to point the server elsewhere, e.g. at the Fixture world's fake Informer API.
    base_url: str = INFORMER_API_URL

    model_config = SettingsConfigDict(
        env_prefix="INFORMER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
