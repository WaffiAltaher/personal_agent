# src/agent/tools/gmail.py
"""
Gmail tools for the personal data agent.

Tools:
  - search_gmail:      search messages using Gmail query syntax
  - get_gmail_message: fetch full content of a message by ID

Read-only (gmail.readonly scope). Write operations (send, reply, draft,
delete) are intentionally excluded — they require human-in-the-loop
confirmation which is implemented in Phase 2.6.

Authentication is shared with Calendar via agent.auth.google.get_google_credentials().

Gmail API returns messages in a two-step pattern:
  1. messages.list()  → returns only message IDs and thread IDs
  2. messages.get()   → returns full message content for a specific ID
This is why we have two tools: search gives you IDs, get gives you content.
Fetching full content for every search result in one tool would flood the
context window on broad queries.

Message bodies in Gmail are base64url-encoded and may be nested in MIME
multipart structures. We decode and extract plain text here so the LLM
receives readable content rather than raw MIME.
"""

import base64
import email as email_lib
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field

from agent.auth.google import get_google_credentials
from fixture_world import google as fixture_google


def _get_gmail_service():
    """Build and return an authenticated Gmail API service client."""
    creds = get_google_credentials()
    return build("gmail", "v1", credentials=creds)


def _decode_body(part: dict) -> str:
    """
    Decode a base64url-encoded message body part into a plain string.
    Returns empty string if decoding fails.
    """
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_plain_text(payload: dict) -> str:
    """
    Recursively extract plain text from a MIME message payload.

    Gmail messages can be:
    - Simple: payload has a body directly (text/plain or text/html)
    - Multipart: payload has parts[], each of which may itself be multipart

    We prefer text/plain over text/html. If only HTML is available, we
    return it as-is (the LLM can read it, though it's noisier).
    """
    mime_type = payload.get("mimeType", "")

    # Simple text part
    if mime_type == "text/plain":
        return _decode_body(payload)

    # HTML fallback — only if no plain text found at this level
    if mime_type == "text/html":
        return _decode_body(payload)

    # Multipart — recurse into parts, prefer plain text
    if "parts" in payload:
        plain = ""
        html = ""
        for part in payload["parts"]:
            extracted = _extract_plain_text(part)
            if part.get("mimeType") == "text/plain" and extracted:
                plain = extracted
            elif part.get("mimeType") == "text/html" and extracted:
                html = extracted
            elif extracted and not plain:
                plain = extracted
        return plain or html

    return ""


def _extract_header(headers: list[dict], name: str) -> str:
    """Extract a named header value from the Gmail headers list."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# search_gmail
# ---------------------------------------------------------------------------

class SearchGmailInput(BaseModel):
    query: str = Field(
        description=(
            "Gmail search query. Uses the same syntax as the Gmail search box. "
            "Examples: "
            "'is:unread' — unread messages; "
            "'from:boss@company.com' — from a specific sender; "
            "'subject:standup after:2024/01/01' — subject filter with date; "
            "'has:attachment is:unread' — unread with attachments. "
            "Combine filters with spaces (implicit AND) or OR."
        )
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of messages to return. Defaults to 10, maximum 50.",
        ge=1,
        le=50,
    )


@tool("search_gmail", args_schema=SearchGmailInput)
def search_gmail(query: str, max_results: int = 10) -> str:
    """
    Search Gmail messages using Gmail query syntax.

    Returns a list of matching messages with sender, date, subject, and
    message ID. Use the message ID with get_gmail_message to read the
    full content of a specific message.

    On failure returns a string beginning with "Error:".
    """
    try:
        service = _get_gmail_service()

        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = result.get("messages", [])

        if not messages:
            return f"No messages found for query: '{query}'"

        lines = [f"Gmail search results for '{query}':", ""]

        for msg_stub in messages:
            msg_id = msg_stub["id"]

            # Fetch metadata only (headers) — not the full body.
            # This keeps the search tool fast and light on tokens.
            # Use get_gmail_message for full content.
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="metadata",
                     metadataHeaders=["From", "To", "Subject", "Date"])
                .execute()
            )

            headers = msg.get("payload", {}).get("headers", [])
            subject = _extract_header(headers, "Subject") or "(No subject)"
            sender = _extract_header(headers, "From") or "Unknown"
            date = _extract_header(headers, "Date") or "Unknown"
            snippet = msg.get("snippet", "")

            lines.append(f"ID:      {msg_id}")
            lines.append(f"From:    {sender}")
            lines.append(f"Date:    {date}")
            lines.append(f"Subject: {subject}")
            if snippet:
                lines.append(f"Preview: {snippet[:120]}...")
            lines.append("")

        return "\n".join(lines).rstrip()

    except HttpError as e:
        return f"Error: Gmail API error {e.status_code}: {e.reason}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# create_draft_email
# ---------------------------------------------------------------------------
# This is a WRITE operation — it is declared a Write action in LOCAL_TOOLS
# (agent/tools/__init__.py), so the agent will always pause for human
# confirmation before this tool executes.

class CreateDraftEmailInput(BaseModel):
    to: str = Field(
        description="Recipient email address."
    )
    subject: str = Field(
        description="Email subject line."
    )
    body: str = Field(
        description="Plain text body of the email."
    )
    cc: str = Field(
        default="",
        description="Optional CC recipients, comma-separated. Leave empty if not needed."
    )


@tool("create_draft_email", args_schema=CreateDraftEmailInput)
def create_draft_email(to: str, subject: str, body: str, cc: str = "") -> str:
    """
    Create a draft email in Gmail. The draft is saved but NOT sent —
    the user can review and send it manually from Gmail, or a future
    send_email tool (with its own HITL approval) can send it.

    This tool requires human approval before execution (it is a Write action).

    On success returns a confirmation with the draft ID.
    On failure returns a string beginning with "Error:".
    """
    try:
        service = _get_gmail_service()

        # Build a MIME message — the Gmail API requires base64url-encoded RFC 2822
        mime_message = MIMEText(body, "plain", "utf-8")
        mime_message["to"] = to
        mime_message["subject"] = subject
        if cc:
            mime_message["cc"] = cc

        # Encode to base64url as required by the Gmail API
        raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("utf-8")

        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )

        draft_id = draft.get("id", "unknown")
        return (
            f"Draft created successfully.\n"
            f"Draft ID: {draft_id}\n"
            f"To:       {to}\n"
            f"Subject:  {subject}\n"
            "The draft is saved in your Gmail Drafts folder. "
            "It has NOT been sent."
        )

    except HttpError as e:
        return f"Error: Gmail API error {e.status_code}: {e.reason}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# get_gmail_message
# ---------------------------------------------------------------------------

class GetGmailMessageInput(BaseModel):
    message_id: str = Field(
        description=(
            "The unique ID of the Gmail message to retrieve. "
            "Get this from the ID field returned by search_gmail."
        )
    )


@tool("get_gmail_message", args_schema=GetGmailMessageInput)
def get_gmail_message(message_id: str) -> str:
    """
    Get the full content of a Gmail message by its ID.

    Returns sender, recipients, date, subject, and decoded body text.
    Use this after search_gmail when you need to read the actual content
    of a specific message.

    On failure returns a string beginning with "Error:".
    """
    try:
        service = _get_gmail_service()

        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        subject = _extract_header(headers, "Subject") or "(No subject)"
        sender = _extract_header(headers, "From") or "Unknown"
        to = _extract_header(headers, "To") or "Unknown"
        date = _extract_header(headers, "Date") or "Unknown"
        cc = _extract_header(headers, "Cc")

        body = _extract_plain_text(payload)

        # Truncate very long bodies to avoid flooding the context window.
        # 4000 chars ≈ ~1000 tokens, enough for most emails.
        max_body_chars = 4000
        truncated = False
        if len(body) > max_body_chars:
            body = body[:max_body_chars]
            truncated = True

        lines = [
            f"From:    {sender}",
            f"To:      {to}",
            f"Date:    {date}",
            f"Subject: {subject}",
        ]
        if cc:
            lines.append(f"Cc:      {cc}")
        lines.append("")
        lines.append(body.strip())
        if truncated:
            lines.append(f"\n[Message truncated at {max_body_chars} characters]")

        return "\n".join(lines)

    except HttpError as e:
        if e.status_code == 404:
            return f"Error: message not found (ID: {message_id})"
        return f"Error: Gmail API error {e.status_code}: {e.reason}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


fixture_search_gmail = StructuredTool.from_function(
    func=fixture_google.search_gmail,
    name=search_gmail.name,
    description=search_gmail.description,
    args_schema=SearchGmailInput,
)
fixture_get_gmail_message = StructuredTool.from_function(
    func=fixture_google.get_gmail_message,
    name=get_gmail_message.name,
    description=get_gmail_message.description,
    args_schema=GetGmailMessageInput,
)
fixture_create_draft_email = StructuredTool.from_function(
    func=fixture_google.create_draft_email,
    name=create_draft_email.name,
    description=create_draft_email.description,
    args_schema=CreateDraftEmailInput,
)
