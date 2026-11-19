"""`python -m agent.web.set_password`: the owner's password, as an argon2id hash in `.env`."""

import pytest
from argon2 import PasswordHasher

from agent.config import Settings
from agent.web.set_password import set_password

FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def typed(*answers):
    """Stand in for the owner at the hidden password prompts; records the prompts shown."""
    remaining = list(answers)
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        return remaining.pop(0)
    read.prompts = prompts
    return read


def test_writes_an_argon2id_hash_that_settings_read_back_and_that_verifies(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GOOGLE_API_KEY=abc\nMODEL_NAME=claude_code:sonnet\n")
    read = typed("s3cret pass", "s3cret pass")

    set_password(env, read=read, hasher=FAST_HASHER)

    assert len(read.prompts) == 2
    stored = Settings(_env_file=env).web_password_hash
    assert stored.startswith("$argon2id$")
    assert PasswordHasher().verify(stored, "s3cret pass")
    lines = env.read_text().splitlines()
    assert lines[:2] == ["GOOGLE_API_KEY=abc", "MODEL_NAME=claude_code:sonnet"]


def test_replaces_only_the_existing_hash_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text("WEB_PORT=8001\nWEB_PASSWORD_HASH='old'\n# a comment\nMAX_ITERATIONS=7")

    set_password(env, read=typed("new pass", "new pass"), hasher=FAST_HASHER)

    lines = env.read_text().splitlines()
    assert [line for line in lines if not line.startswith("WEB_PASSWORD_HASH=")] == ["WEB_PORT=8001", "# a comment", "MAX_ITERATIONS=7"]
    assert lines[1].startswith("WEB_PASSWORD_HASH='$argon2id$")
    assert PasswordHasher().verify(Settings(_env_file=env).web_password_hash, "new pass")


def test_creates_the_env_file_when_there_is_none(tmp_path):
    env = tmp_path / ".env"

    set_password(env, read=typed("pw pw pw", "pw pw pw"), hasher=FAST_HASHER)

    assert PasswordHasher().verify(Settings(_env_file=env).web_password_hash, "pw pw pw")


@pytest.mark.parametrize("answers", [("one", "two"), ("", "")])
def test_a_mismatch_or_an_empty_password_changes_nothing(tmp_path, capsys, answers):
    env = tmp_path / ".env"
    env.write_text("A=1\n")

    with pytest.raises(SystemExit) as exited:
        set_password(env, read=typed(*answers), hasher=FAST_HASHER)

    assert exited.value.code == 1
    assert env.read_text() == "A=1\n"
    assert capsys.readouterr().out.strip()
