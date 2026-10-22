# src/agent/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # LLM
    google_api_key: str
    anthropic_api_key: str | None = None  # required only when an anthropic: model is selected

    # Tools
    tavily_api_key: str

    # Langfuse observability
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str = "http://localhost:3000"

    # Agent behaviour (sensible defaults for now)
    model_name: str = "google_genai:gemini-3.8-flash"  # provider:model, see agent/chat_model.py
    max_iterations: int = 10

    # Memory layer
    sqlite_path: str = "data/episodic.db"
    chroma_path: str = "data/chroma"
    chroma_embedding_model: str = "models/gemini-embedding-001"
    memory_score_threshold: float = 0.7
    memory_top_k: int = 5

    # Evals: provider:model that grades answers (RAGAS); None → the model under test, with a warning.
    # `--judge-model` overrides it. Answer relevancy embeds with chroma_embedding_model.
    eval_judge_model: str | None = None

    # Context window pressure limits
    context_warning_threshold: int = 100_000
    context_hard_limit: int = 800_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    prompt_version: str = "v4"  # see agent/prompts.py; tagged on each Langfuse trace
    # Optional: without them the agent starts without MS365 tools, with a notice.
    ms365_mcp_client_id: str | None = None
    ms365_mcp_tenant_id: str | None = None
    # Optional: the Microsoft account the server must be logged in as (fails fast on another one).
    ms365_mcp_expected_username: str | None = None
    # Optional: without them the agent starts without Informer tools, with a notice.
    informer_api_key: str | None = None
    informer_security_code: str | None = None


settings = Settings()