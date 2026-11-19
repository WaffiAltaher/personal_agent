"""
set_password.py — ``python -m agent.web.set_password`` sets the web interface's password.

Reads the password twice without echo and writes its argon2id hash to ``.env`` as
``WEB_PASSWORD_HASH``, replacing that line if there is one and leaving every other line as it
was. A new password ends every web session (the session key is derived from the hash).
"""

import getpass
import sys
from collections.abc import Callable
from pathlib import Path

from argon2 import PasswordHasher

from agent.config import PROJECT_ROOT

ENV_KEY = "WEB_PASSWORD_HASH"


def set_password(
    env_path: Path = PROJECT_ROOT / ".env",
    *,
    read: Callable[[str], str] = getpass.getpass,
    hasher: PasswordHasher | None = None,
) -> None:
    password = read("New web password: ")
    if not password:
        print("No password given; nothing changed.")
        sys.exit(1)
    if read("Repeat it: ") != password:
        print("The passwords differ; nothing changed.")
        sys.exit(1)
    password_hash = (hasher or PasswordHasher()).hash(password)  # argon2id by default
    # Single quotes: the hash is full of `$`, which .env readers must not expand.
    line = f"{ENV_KEY}='{password_hash}'"

    lines = env_path.read_text().splitlines() if env_path.exists() else []
    replaced = False
    for i, existing in enumerate(lines):
        if existing.split("=", 1)[0].strip() == ENV_KEY:
            lines[i] = line
            replaced = True
    if not replaced:
        lines.append(line)
    env_path.write_text("\n".join(lines) + "\n")
    print(f"Password set in {env_path}. Existing web sessions have ended; restart the web server.")


if __name__ == "__main__":
    set_password()
