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


def test_the_env_file_is_the_repo_s_whatever_the_working_directory():
    assert Path(Settings.model_config["env_file"]) == REPO / ".env"
    assert Path(InformerSettings.model_config["env_file"]) == REPO / ".env"
