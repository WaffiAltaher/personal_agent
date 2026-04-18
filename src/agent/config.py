# src/agent/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # LLM
    google_api_key: str

    # Tools
    tavily_api_key: str

    # Langfuse observability
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str = "http://localhost:3000"

    # Agent behaviour (sensible defaults for now)
    model_name: str = "gemini-2.0-flash"
    max_iterations: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

settings = Settings()