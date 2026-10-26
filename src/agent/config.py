# src/agent/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # LLM
    google_api_key: str  # always required, whatever model_name is: the memory layer embeds with it
    anthropic_api_key: str | None = None  # required only when an anthropic: model is selected

    # Tools
    tavily_api_key: str

    # Langfuse observability
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str = "http://localhost:3000"

    # Agent behaviour (sensible defaults for now)
    model_name: str = "claude_code:claude-sonnet-5-5"  # provider:model, see agent/chat_model.py
    max_iterations: int = 10
    # claude_code: models (agent/claude_code_model.py): the Claude Code CLI, and how long one call may take
    claude_code_binary: str = "claude"
    claude_code_timeout_s: float = 180

    # Memory layer
    sqlite_path: str = "data/episodic.db"
    chroma_path: str = "data/chroma"
    chroma_embedding_model: str = "models/gemini-embedding-001"
    # Chosen to sit above unrelated scores on the synthetic CalibrationEmbeddings
    # fixture (tests/memory/test_cosine_threshold.py); live embedding calibration
    # is a follow-up when a real API key is available in CI.
    memory_score_threshold: float = 0.7
    memory_top_k: int = 5
    memory_budget: int = 10_000

    # Evals: provider:model that grades answers (RAGAS); None → the model under test, with a warning.
    # `--judge-model` overrides it. Answer relevancy embeds with chroma_embedding_model.
    eval_judge_model: str | None = None

    # The agent's own folder: saved email attachments go into its gmail/ and outlook/ subfolders.
    # Tests and evals point it at a temporary directory.
    agent_folder: str = "~/Downloads/personal_agent"

    # Context view limits (ADR-013): reduce tool results in the model view only
    context_clear_threshold: int = 100_000
    context_clear_target: int = 50_000
    tool_result_max_tokens: int = 20_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    prompt_version: str = "v5"  # see agent/prompts.py; tagged on each Langfuse trace
    # Optional: without them the agent starts without MS365 tools, with a notice.
    ms365_mcp_client_id: str | None = None
    ms365_mcp_tenant_id: str | None = None
    # Optional: the Microsoft account the server must be logged in as (fails fast on another one).
    ms365_mcp_expected_username: str | None = None
    # Optional: without them the agent starts without Informer tools, with a notice.
    informer_api_key: str | None = None
    informer_security_code: str | None = None


settings = Settings()