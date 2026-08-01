"""
Gmail integration.

Setup (do this ONCE, before any demo — see AGENT_SETUP.md / README):
1. Create a free Google Cloud project, enable the Gmail API.
2. OAuth consent screen -> "Testing" mode, add your own Gmail account(s)
   as test users. No verification needed for testing mode.
3. Create OAuth Client ID (Desktop app type), download as
   gmail_client_secret.json into the data root.
4. Run `python -m modules.gmail_client --authorize` once. This opens a
   browser for the one-time consent click and saves gmail_token.json.
   After that, everything below runs silently, no browser popups.

IMPORTANT: point this at test mailboxes you control while developing and
demoing (a second Gmail account standing in as "Police Dept"), not real
government/department addresses, until this is an actual authorized
deployment.
"""
import base64
import os
from email.mime.text import MIMEText
from pathlib import Path

from config import get_data_root, GMAIL_TOKEN_FILENAME, GMAIL_CLIENT_SECRET_FILENAME

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GMAIL_LIBS_AVAILABLE = True
except ImportError:
    GMAIL_LIBS_AVAILABLE = False


def _token_path() -> Path:
    return get_data_root() / GMAIL_TOKEN_FILENAME


def _client_secret_path() -> Path:
    return get_data_root() / GMAIL_CLIENT_SECRET_FILENAME


def is_configured() -> bool:
    return GMAIL_LIBS_AVAILABLE and _token_path().exists()


def authorize_once():
    """Run this manually, once, ahead of any demo — opens a browser for
    consent and saves a reusable token. Never call this from the
    server/frontend process itself (that would trigger a live popup)."""
    if not GMAIL_LIBS_AVAILABLE:
        raise RuntimeError("Gmail libraries not installed. See requirements.txt.")
    if not _client_secret_path().exists():
        raise RuntimeError(
            f"Missing {GMAIL_CLIENT_SECRET_FILENAME} in data root. "
            "Download it from Google Cloud Console (OAuth Client ID, Desktop app)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(_client_secret_path()), SCOPES)
    creds = flow.run_local_server(port=0)
    _token_path().write_text(creds.to_json())
    print(f"Authorized. Token saved to {_token_path()}")


def _get_service():
    if not is_configured():
        raise RuntimeError("Gmail not authorized yet. Run authorize_once() first.")
    creds = Credentials.from_authorized_user_file(str(_token_path()), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _token_path().write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def send_email(to_email: str, subject: str, body: str, thread_id: str = None) -> dict:
    """Sends an email, optionally continuing an existing thread. Returns
    the Gmail API message resource (includes 'id' and 'threadId')."""
    service = _get_service()
    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body_payload = {"raw": raw}
    if thread_id:
        body_payload["threadId"] = thread_id
    return service.users().messages().send(userId="me", body=body_payload).execute()


def list_new_messages_in_thread(thread_id: str, known_message_ids: set):
    """Returns message resources in this thread not already in
    known_message_ids, so the scheduler can detect genuinely new replies."""
    service = _get_service()
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    new_messages = []
    for msg in thread.get("messages", []):
        if msg["id"] not in known_message_ids:
            new_messages.append(msg)
    return new_messages


def extract_attachments(message: dict, save_dir: str) -> list:
    """Pulls any file attachments out of a Gmail message resource and saves
    them to save_dir. Returns list of saved file paths."""
    service = _get_service()
    saved_paths = []
    parts = message.get("payload", {}).get("parts", []) or []
    for part in parts:
        filename = part.get("filename")
        body = part.get("body", {})
        if filename and body.get("attachmentId"):
            att = service.users().messages().attachments().get(
                userId="me", messageId=message["id"], id=body["attachmentId"]
            ).execute()
            data = base64.urlsafe_b64decode(att["data"])
            out_path = os.path.join(save_dir, filename)
            with open(out_path, "wb") as f:
                f.write(data)
            saved_paths.append(out_path)
    return saved_paths


def extract_attachments_routed(message: dict, case_dir) -> list:
    """Like extract_attachments, but saves each file into the case's
    evidence/images, evidence/documents, or evidence/other subfolder based
    on its extension, so received evidence lands in the same elaborated
    folder structure as manually uploaded evidence."""
    import config as config_mod

    service = _get_service()
    saved_paths = []
    parts = message.get("payload", {}).get("parts", []) or []
    for part in parts:
        filename = part.get("filename")
        body = part.get("body", {})
        if filename and body.get("attachmentId"):
            att = service.users().messages().attachments().get(
                userId="me", messageId=message["id"], id=body["attachmentId"]
            ).execute()
            data = base64.urlsafe_b64decode(att["data"])
            subfolder = config_mod.evidence_subfolder_for_filename(filename)
            dest_dir = case_dir / subfolder
            dest_dir.mkdir(parents=True, exist_ok=True)
            out_path = dest_dir / filename
            out_path.write_bytes(data)
            saved_paths.append(str(out_path))
    return saved_paths


def extract_plain_text(message: dict) -> str:
    """Best-effort plain text extraction from a Gmail message payload."""
    payload = message.get("payload", {})

    def _walk(part):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(errors="ignore")
        for sub in part.get("parts", []) or []:
            result = _walk(sub)
            if result:
                return result
        return ""

    return _walk(payload)


if __name__ == "__main__":
    import sys
    if "--authorize" in sys.argv:
        authorize_once()
    else:
        print("Usage: python -m modules.gmail_client --authorize")
