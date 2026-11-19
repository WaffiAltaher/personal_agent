"""The eval's file tools: the real tools' names and descriptions, confined to the files root."""

import pytest

from agent.tools.filesystem import (
    FILES_ROOT_ENV,
    fixture_list_directory,
    fixture_read_file,
    list_directory,
    read_file,
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    files = tmp_path / "Downloads"
    files.mkdir()
    (files / "note.txt").write_text("seeded")
    (tmp_path / "secret.txt").write_text("owner data")
    monkeypatch.setenv(FILES_ROOT_ENV, str(files))
    return files


def test_the_stand_ins_look_like_the_real_tools_to_the_model():
    assert (fixture_read_file.name, fixture_read_file.description) == (read_file.name, read_file.description)
    assert (fixture_list_directory.name, fixture_list_directory.description) == (
        list_directory.name, list_directory.description)
    assert fixture_read_file.args == read_file.args
    assert fixture_list_directory.args == list_directory.args


def test_a_file_inside_the_root_is_read_by_absolute_or_relative_path(root):
    assert fixture_read_file.invoke({"path": str(root / "note.txt")}) == "seeded"
    assert fixture_read_file.invoke({"path": "note.txt"}) == "seeded"
    assert "note.txt" in fixture_list_directory.invoke({"path": str(root)})


@pytest.mark.parametrize("path", ["../secret.txt", "SECRET", "~/.ssh/id_rsa", "/etc/hosts"])
def test_a_path_outside_the_root_is_not_found(root, path):
    target = str(root.parent / "secret.txt") if path == "SECRET" else path
    result = fixture_read_file.invoke({"path": target})
    assert result.startswith("Error: file not found")
    assert "owner data" not in result
    assert fixture_list_directory.invoke({"path": str(root.parent)}).startswith("Error: path not found")


def test_without_a_root_nothing_is_readable(monkeypatch, tmp_path):
    monkeypatch.delenv(FILES_ROOT_ENV, raising=False)
    (tmp_path / "a.txt").write_text("x")
    assert fixture_read_file.invoke({"path": str(tmp_path / "a.txt")}).startswith("Error:")
