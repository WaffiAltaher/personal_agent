# src/agent/auth/google.py
"""
Google OAuth2 credential management.

This module is the single place responsible for loading, refreshing, and
persisting Google OAuth2 credentials. Both Calendar and Gmail tools import
from here — credentials are not duplicated across tool modules.

Flow (first run):
  1. No token.json exists → open browser → user logs in and grants scopes
  2. Google returns access token + refresh token → saved to token.json

Flow (subsequent runs):
  1. Load token.json
  2. If access token is expired → refresh automatically using refresh token
  3. Save updated token back to token.json
  4. Return valid credentials

The refresh happens transparently. The agent never needs to re-authenticate
unless the refresh token itself is revoked (user revokes access, or the OAuth
app is in Testing mode and 7 days have passed without use).

Scopes are declared here as the single source of truth. If you add a new
scope (e.g. Gmail), add it to SCOPES and delete token.json so the user is
re-prompted to grant the new permission.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

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


def get_google_credentials() -> Credentials:
    """
    Load and return valid Google OAuth2 credentials.

    Handles the full lifecycle:
    - First run: opens browser for user consent, saves token.json
    - Subsequent runs: loads token.json, refreshes if expired
    - Returns credentials ready to pass to googleapiclient.discovery.build()

    Raises:
        FileNotFoundError: if google_credentials.json is missing
        google.auth.exceptions.RefreshError: if the refresh token is revoked
    """
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Google credentials file not found: {CREDENTIALS_FILE}\n"
            "Download it from GCP Console → APIs & Services → Credentials → "
            "your OAuth client → Download JSON, and save it to credentials/google_credentials.json"
        )

    creds = None

    # Load existing token if present
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # If no valid credentials, refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but we have a refresh token — refresh silently
            creds.refresh(Request())
        else:
            # No token at all, or refresh token missing — full OAuth flow
            # This opens a browser window for the user to log in
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Persist the token for the next run
        TOKEN_FILE.write_text(creds.to_json())

    return creds
