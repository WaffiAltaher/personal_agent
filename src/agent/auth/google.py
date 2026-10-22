# src/agent/auth/google.py
"""
Google OAuth2 credential management.

This module is the single place responsible for loading, refreshing, and
persisting Google OAuth2 credentials. Both Calendar and Gmail tools import
from here — credentials are not duplicated across tool modules.

Flow (first run):
  1. No token.json exists → run `python -m agent.auth.google` to log in via the browser
  2. Google returns access token + refresh token → saved to token.json

Flow (subsequent runs):
  1. Load token.json
  2. If access token is expired → refresh automatically using refresh token
  3. Save updated token back to token.json
  4. Return valid credentials

The refresh happens transparently on valid tokens. If the refresh token itself is
revoked (user revokes access, or the OAuth app is in Testing mode and seven days
have passed since issue, regardless of use), the dead token is removed and callers
see an error naming the re-login command — a browser never opens outside that command.

Scopes are declared here as the single source of truth. If you add a new
scope (e.g. Gmail), add it to SCOPES and delete token.json so the user is
re-prompted to grant the new permission.
"""

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

GOOGLE_LOGIN_COMMAND = "python -m agent.auth.google"

# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------
# We request only what we need. Starting with read-only Calendar.
# When we add Gmail in step 2.4, we'll add the Gmail scope here.
# Important: changing scopes requires deleting token.json and re-authenticating.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    # gmail.modify covers read + drafts + labels. We use this instead of
    # gmail.readonly now that we have create_draft_email (a write operation).
    # If you only ever need read access, gmail.readonly is more restrictive.
    # Note: changing scopes requires deleting credentials/token.json and re-authing.
    "https://www.googleapis.com/auth/gmail.modify",
]

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
# Resolve relative to the project root (two levels up from this file:
# src/agent/auth/google.py → src/agent/auth → src/agent → src → project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS_FILE = _PROJECT_ROOT / "credentials" / "google_credentials.json"
TOKEN_FILE = _PROJECT_ROOT / "credentials" / "token.json"


class GoogleLoginRequired(Exception):
    """Google OAuth token is missing or the refresh token is no longer valid."""


def _login_required_message() -> str:
    return (
        f"Not logged in to Google. Log in with `{GOOGLE_LOGIN_COMMAND}`, "
        "then restart the agent."
    )


def _delete_token_file() -> None:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def login_via_browser() -> Credentials:
    """Open the browser OAuth flow and persist a new token. The only browser entry point."""
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Google credentials file not found: {CREDENTIALS_FILE}\n"
            "Download it from GCP Console → APIs & Services → Credentials → "
            "your OAuth client → Download JSON, and save it to credentials/google_credentials.json"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def check_google_login() -> None:
    """Verify Google login before a real CLI run. Raises on missing or dead tokens."""
    get_google_credentials()


def get_google_credentials() -> Credentials:
    """
    Load and return valid Google OAuth2 credentials.

    Refreshes an expired access token when the refresh token is still valid.
    Never opens a browser — use ``login_via_browser()`` (``python -m agent.auth.google``).

    Raises:
        FileNotFoundError: if google_credentials.json is missing
        GoogleLoginRequired: if token.json is missing or the refresh token is dead
    """
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Google credentials file not found: {CREDENTIALS_FILE}\n"
            "Download it from GCP Console → APIs & Services → Credentials → "
            "your OAuth client → Download JSON, and save it to credentials/google_credentials.json"
        )

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                _delete_token_file()
                raise GoogleLoginRequired(_login_required_message()) from None
            TOKEN_FILE.write_text(creds.to_json())
        else:
            raise GoogleLoginRequired(_login_required_message())

    return creds


def main() -> None:
    login_via_browser()
    print("Google login saved. You can restart the agent.")


if __name__ == "__main__":
    main()
