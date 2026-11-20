"""tests/test_config_paths.py — `.env` and the memory files are found from the repo root, not the working directory."""

from pathlib import Path

from agent.config import PROJECT_ROOT, Settings
from informer_mcp.config import InformerSettings

REPO = Path(__file__).resolve().parents[1]


def test_memory_paths_do_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert PROJECT_ROOT == REPO
    assert settings.sqlite_path == str(REPO / "data" / "episodic.db")
    assert settings.chroma_path == str(REPO / "data" / "chroma")


def test_an_absolute_memory_path_is_kept(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=str(tmp_path / "e.db"), chroma_path=str(tmp_path / "chroma"))

    assert settings.sqlite_path == str(tmp_path / "e.db")
    assert settings.chroma_path == str(tmp_path / "chroma")


def test_the_informer_email_addresses_in_the_env_file_do_not_stop_the_agent(tmp_path, monkeypatch):
    """Both read the one `.env`: the addresses are the Informer server's settings (ADR-019)."""
    for name in ("INFORMER_INCOMING_ADDRESS", "INFORMER_INVOICE_MAILBOX"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GOOGLE_API_KEY=google\nTAVILY_API_KEY=tavily\nLANGFUSE_PUBLIC_KEY=pk\nLANGFUSE_SECRET_KEY=sk\n"
        "INFORMER_INCOMING_ADDRESS=adm-91x2@scan.informer.example\n"
        "INFORMER_INVOICE_MAILBOX=inkoop-scan@bedrijf.example\n"
    )

    Settings(_env_file=env_file)
    informer = InformerSettings(_env_file=env_file, api_key="key", security_code="code")

    assert informer.incoming_address == "adm-91x2@scan.informer.example"
    assert informer.invoice_mailbox == "inkoop-scan@bedrijf.example"


def test_the_env_file_is_the_repo_s_whatever_the_working_directory():
    assert Path(Settings.model_config["env_file"]) == REPO / ".env"
    assert Path(InformerSettings.model_config["env_file"]) == REPO / ".env"
