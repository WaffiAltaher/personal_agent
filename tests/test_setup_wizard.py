"""tests/test_setup_wizard.py — the Informer e-mail step of `scripts/setup_wizard.sh` (ADR-019) and the Azure app
stage's Files.ReadWrite (ADR-020).

The seam is the script itself, run as the owner runs it: a scripted owner answers its prompts, the tools it
calls (uv, npx, docker, curl, the browser opener, git) are stand-ins on PATH, and `ENV_FILE` is a temp file.
Nothing reaches a real service.
"""

import os
import re
import select
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WIZARD = REPO / "scripts" / "setup_wizard.sh"

INCOMING = "adm-91x2@scan.informer.example"
MAILBOX = "inkoop-scan@bedrijf.example"
EMAIL_SETTINGS_URL = "https://app.informer.eu/settings/email/"

STAND_INS = {
    # Opens "the browser": records the URL instead.
    "wslview": 'echo "$1" >> "$WIZARD_OPENED"',
    "uv": "exit 0",
    "npx": "exit 0",
    "docker": "exit 0",
    "curl": "exit 0",
    "git": 'echo "feat/complete-phases-5-7"',
}


class Run:
    def __init__(self, output: str, env_file: Path, opened: list[str], returncode: int):
        self.output = output
        self.env_file = env_file
        self.opened = opened
        self.returncode = returncode

    def env_lines(self) -> list[str]:
        return self.env_file.read_text().splitlines() if self.env_file.exists() else []


@pytest.fixture
def wizard(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STAND_INS.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    env_file = tmp_path / ".env"
    opened_file = tmp_path / "opened.txt"

    def run(answers: dict[str, str], env_text: str | None = None) -> Run:
        """Answer each prompt whose text contains a key of `answers`; anything else gets Enter (the default)."""
        if env_text is not None:
            env_file.write_text(env_text)
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "ENV_FILE": str(env_file),
            "WIZARD_OPENED": str(opened_file),
        }
        proc = subprocess.Popen(
            ["bash", str(WIZARD)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
        )
        out = ""
        line_start = 0
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], 0.1)
            if ready:
                chunk = os.read(proc.stdout.fileno(), 4096)
                if not chunk:
                    break
                out += chunk.decode()
                continue
            if proc.poll() is not None:
                break
            # Output went quiet mid-line: the wizard is waiting at a prompt.
            prompt = out[out.rfind("\n") + 1 :] if not out.endswith("\n") else ""
            if prompt and len(out) > line_start:
                line_start = len(out)
                answer = next((a for text, a in answers.items() if text in prompt), "")
                proc.stdin.write(f"{answer}\n".encode())
                proc.stdin.flush()
        proc.wait(timeout=10)
        opened = opened_file.read_text().splitlines() if opened_file.exists() else []
        return Run(out, env_file, opened, proc.returncode)

    return run


BASE_ANSWERS = {"Paste the Google API key": "google-key"}


def test_the_informer_email_step_writes_the_two_addresses_to_env(wizard):
    result = wizard(
        {
            **BASE_ANSWERS,
            "Set up the Informer e-mail upload": "y",
            "Paste the Informer incoming address": INCOMING,
            "Invoice mailbox": MAILBOX,
        }
    )

    assert result.returncode == 0
    assert f"INFORMER_INCOMING_ADDRESS={INCOMING}" in result.env_lines()
    assert f"INFORMER_INVOICE_MAILBOX={MAILBOX}" in result.env_lines()
    assert EMAIL_SETTINGS_URL in result.opened


def test_the_informer_email_step_can_be_skipped(wizard):
    result = wizard(BASE_ANSWERS)

    assert result.returncode == 0
    assert not [line for line in result.env_lines() if line.startswith(("INFORMER_INCOMING", "INFORMER_INVOICE"))]
    assert EMAIL_SETTINGS_URL not in result.opened


def test_the_informer_email_step_replaces_only_its_two_lines(wizard):
    before = (
        "WEB_PORT=9000\n"
        "INFORMER_INCOMING_ADDRESS=old-incoming@scan.informer.example\n"
        "TAVILY_API_KEY=tavily\n"
        "INFORMER_INVOICE_MAILBOX=old-mailbox@bedrijf.example\n"
        "LANGFUSE_SECRET_KEY=sk\n"
    )
    result = wizard(
        {
            "Set up the Informer e-mail upload": "y",
            "Paste the Informer incoming address": INCOMING,
            "Invoice mailbox": MAILBOX,
            "Paste the Google API key": "google-key",
        },
        env_text=before,
    )

    lines = result.env_lines()
    assert [line for line in lines if line.startswith("INFORMER_INCOMING")] == [f"INFORMER_INCOMING_ADDRESS={INCOMING}"]
    assert [line for line in lines if line.startswith("INFORMER_INVOICE")] == [f"INFORMER_INVOICE_MAILBOX={MAILBOX}"]
    # Lines no wizard step owns are still there, once, with their value.
    for kept in ("WEB_PORT=9000", "TAVILY_API_KEY=tavily"):
        assert lines.count(kept) == 1


def test_the_incoming_address_is_not_echoed_and_the_step_warns_it_is_a_write_key(wizard):
    result = wizard(
        {
            **BASE_ANSWERS,
            "Set up the Informer e-mail upload": "y",
            "Paste the Informer incoming address": INCOMING,
            "Invoice mailbox": MAILBOX,
        }
    )

    assert INCOMING not in result.output
    assert re.search(r"write key", result.output)
    assert re.search(r"commit", result.output)


def test_the_stage_counter_matches_the_stages_shown(wizard):
    result = wizard(BASE_ANSWERS)

    stages = [(int(i), int(n)) for i, n in re.findall(r"Stage (\d+)/(\d+)", result.output)]
    assert stages
    assert {total for _, total in stages} == {stages[-1][0]}


def test_the_azure_stage_adds_files_readwrite_for_the_invoice_archive(wizard):
    """A fresh setup grants the delegated Files.ReadWrite the drive tools request (ADR-020)."""
    result = wizard(BASE_ANSWERS)

    azure = result.output[result.output.index("Azure app") : result.output.index("one-time login")]
    assert re.search(r"[Ss]earch 'Files\.ReadWrite' → tick it → Add permissions", azure)
    assert re.search(r"Files\.ReadWrite are listed", azure)
    assert re.search(r"not Files\.ReadWrite\.All", azure)
