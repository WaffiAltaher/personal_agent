# src/agent/config.py
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root (src/agent/config.py → src/agent → src → root). `.env` and the memory files are
# found from here, not from the working directory: started elsewhere, the agent would otherwise
# miss its `.env` and open a new, empty memory there.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
    # google_genai: and anthropic: models, and the Google embeddings: how long one API request may
    # take. Both integrations default to no timeout, so a request the server never answers would hang.
    model_timeout_s: float = 120
    # Every model and the Google embeddings: how many times (the first included) one request is
    # tried when it fails in a way worth retrying, e.g. a timeout or an overloaded server's 503.
    model_attempts: int = 2

    # Memory layer
    sqlite_path: str = "data/episodic.db"
    chroma_path: str = "data/chroma"
    chroma_embedding_model: str = "models/gemini-embedding-001"
    # Chosen to sit above unrelated scores on the synthetic CalibrationEmbeddings
    # fixture (tests/memory/test_cosine_threshold.py); live embedding calibration
    # is a follow-up when a real API key is available in CI.
    memory_score_threshold: float = 0.7

    @field_validator("model_attempts")
    @classmethod
    def _at_least_one_attempt(cls, value: int) -> int:
        if value < 1:
            raise ValueError("MODEL_ATTEMPTS must be at least 1")
        return value

    @field_validator("sqlite_path", "chroma_path")
    @classmethod
    def _relative_to_project_root(cls, value: str) -> str:
        """A relative memory path is relative to the repo root; an absolute one is kept."""
        return str(PROJECT_ROOT / Path(value).expanduser())

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
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
    )

    prompt_version: str = "v6"  # see agent/prompts.py; tagged on each Langfuse trace
    # Optional: without them the agent starts without MS365 tools, with a notice.
    ms365_mcp_client_id: str | None = None
    ms365_mcp_tenant_id: str | None = None
    # Optional: the Microsoft account the server must be logged in as (fails fast on another one).
    ms365_mcp_expected_username: str | None = None
    # Optional: without them the agent starts without Informer tools, with a notice.
    informer_api_key: str | None = None
    informer_security_code: str | None = None
    # Web interface (python -m agent.web, ADR-018). The owner's password as an argon2id hash, set
    # with `python -m agent.web.set_password`; the server refuses to start without it.
    web_password_hash: str | None = None
    web_port: int = 8000
    # Keep 127.0.0.1 until Sign in with Google replaces the password: the setting is for deploying online.
    web_host: str = "127.0.0.1"


settings = Settings()