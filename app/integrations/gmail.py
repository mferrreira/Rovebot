from __future__ import annotations

import base64
import logging
import threading
import time
import webbrowser
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header as _decode_header, make_header as _make_header
from email.utils import parseaddr
from email.message import Message
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from app.models.email import Email

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
_REDIRECT_PORT = 8080
_REDIRECT_URI = f"http://localhost:{_REDIRECT_PORT}/callback"

logger = logging.getLogger(__name__)


def _decode_mime_words(value: str) -> str:
    """Decode RFC 2047 encoded header value (e.g. =?UTF-8?Q?...?=)."""
    try:
        return str(_make_header(_decode_header(value)))
    except Exception:
        return value


class GmailApiClient:
    def __init__(
        self,
        api_base_url: str,
        access_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        timeout: float = 10.0,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.timeout = timeout
        self._label_cache: dict[str, str] = {}

        if not self.access_token and self.refresh_token:
            logger.info("No access token — refreshing via refresh token")
            self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        response = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        self.access_token = response.json()["access_token"]
        logger.info("Gmail access token refreshed")

    def fetch_email(self, message_id: str) -> Email:
        message_response = self._get(f"/users/me/messages/{message_id}?format=raw")
        message_payload = message_response.json()
        raw_bytes = base64.urlsafe_b64decode(message_payload["raw"])
        mime_message = message_from_bytes(raw_bytes)
        thread_id = message_payload.get("threadId", message_id)
        thread_history = self._fetch_thread(thread_id)
        return Email(
            message_id=message_id,
            thread_id=thread_id,
            sender=_decode_mime_words(str(mime_message.get("From", ""))),
            subject=_decode_mime_words(str(mime_message.get("Subject", ""))),
            body=self._extract_body(mime_message),
            thread_history=thread_history,
            received_at=datetime.now(timezone.utc),
        )

    def get_history_id(self) -> str:
        return str(self._get("/users/me/profile").json()["historyId"])

    def fetch_new_message_ids(self, history_id: str) -> list[str]:
        payload = self._get(
            f"/users/me/history?startHistoryId={history_id}&historyTypes=messageAdded"
        ).json()
        ids: list[str] = []
        for record in payload.get("history", []):
            for added in record.get("messagesAdded", []):
                message = added.get("message", {})
                label_ids = set(message.get("labelIds", []))
                # Only process real inbox arrivals. Sent/draft messages also appear in
                # history and can cause the bot to answer the user's own outbound email.
                if "INBOX" not in label_ids or {"SENT", "DRAFT"} & label_ids:
                    continue
                message_id = message.get("id")
                if message_id:
                    ids.append(message_id)
        return ids

    def ensure_label(self, name: str) -> str:
        if name in self._label_cache:
            return self._label_cache[name]
        for label in self._get("/users/me/labels").json().get("labels", []):
            if label["name"] == name:
                self._label_cache[name] = label["id"]
                return label["id"]
        logger.info("creating Gmail label %r", name)
        label_id: str = self._post(
            "/users/me/labels",
            {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).json()["id"]
        self._label_cache[name] = label_id
        return label_id

    def apply_label(self, message_id: str, label_name: str) -> None:
        label_id = self.ensure_label(label_name)
        self._post(f"/users/me/messages/{message_id}/modify", {"addLabelIds": [label_id]})

    def create_draft(self, to: str, subject: str, body: str, thread_id: str) -> str:
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        _, to_addr = parseaddr(to)
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to_addr
        msg["Subject"] = reply_subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return str(self._post(
            "/users/me/drafts",
            {"message": {"raw": raw, "threadId": thread_id}},
        ).json()["id"])

    def send_draft(self, draft_id: str) -> None:
        self._post("/users/me/drafts/send", {"id": draft_id})

    def update_draft(self, draft_id: str, to: str, subject: str, body: str, thread_id: str) -> None:
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        _, to_addr = parseaddr(to)
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to_addr
        msg["Subject"] = reply_subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self._put(f"/users/me/drafts/{draft_id}", {"message": {"raw": raw, "threadId": thread_id}})

    def _fetch_thread(self, thread_id: str) -> list[str]:
        items: list[str] = []
        for message in self._get(f"/users/me/threads/{thread_id}?format=metadata").json().get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            if sender or subject:
                items.append(f"From {sender}: {subject}")
        return items

    def _get(self, path: str, _retries: int = 3) -> httpx.Response:
        response = self._do_get(path)
        if response.status_code == 401 and self.refresh_token:
            logger.warning("Gmail 401 on GET %s — refreshing token", path)
            self._refresh_access_token()
            response = self._do_get(path)
        if response.status_code >= 500 and _retries > 1:
            wait = 2 ** (4 - _retries)
            logger.warning("Gmail %s on GET %s — retrying in %ss", response.status_code, path, wait)
            time.sleep(wait)
            return self._get(path, _retries=_retries - 1)
        response.raise_for_status()
        return response

    def _post(self, path: str, body: dict) -> httpx.Response:
        response = self._do_post(path, body)
        if response.status_code == 401 and self.refresh_token:
            logger.warning("Gmail 401 on POST %s — refreshing token", path)
            self._refresh_access_token()
            response = self._do_post(path, body)
        if not response.is_success:
            logger.error("Gmail %s on POST %s — body: %s", response.status_code, path, response.text)
        response.raise_for_status()
        return response

    def _do_get(self, path: str) -> httpx.Response:
        return httpx.get(
            f"{self.api_base_url}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=self.timeout,
        )

    def _do_post(self, path: str, body: dict) -> httpx.Response:
        return httpx.post(
            f"{self.api_base_url}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json=body,
            timeout=self.timeout,
        )

    def _put(self, path: str, body: dict) -> httpx.Response:
        response = self._do_put(path, body)
        if response.status_code == 401 and self.refresh_token:
            logger.warning("Gmail 401 on PUT %s — refreshing token", path)
            self._refresh_access_token()
            response = self._do_put(path, body)
        if not response.is_success:
            logger.error("Gmail %s on PUT %s — body: %s", response.status_code, path, response.text)
        response.raise_for_status()
        return response

    def _do_put(self, path: str, body: dict) -> httpx.Response:
        return httpx.put(
            f"{self.api_base_url}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json=body,
            timeout=self.timeout,
        )

    def _extract_body(self, message: Message) -> str:
        if message.is_multipart():
            parts: list[str] = []
            for part in message.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
            return "\n".join(parts).strip()
        payload = message.get_payload(decode=True)
        if not payload:
            return ""
        return payload.decode(message.get_content_charset() or "utf-8", errors="ignore").strip()


def run_oauth_flow(client_id: str, client_secret: str) -> tuple[str, str]:
    """Open browser for OAuth consent, return (access_token, refresh_token)."""
    auth_code: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/callback":
                params = parse_qs(parsed.query)
                code = params.get("code", [None])[0]
                if code:
                    auth_code.append(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization complete!</h1><p>You can close this tab.</p>")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("localhost", _REDIRECT_PORT), _Handler)

    auth_url = (
        f"{_AUTH_URL}"
        f"?client_id={client_id}"
        f"&redirect_uri={_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={_OAUTH_SCOPE}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print("Opening browser for Gmail authorization...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)
    server.serve_forever()

    if not auth_code:
        raise RuntimeError("No authorization code received.")

    response = httpx.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": auth_code[0],
            "grant_type": "authorization_code",
            "redirect_uri": _REDIRECT_URI,
        },
    )
    response.raise_for_status()
    tokens = response.json()
    return tokens["access_token"], tokens["refresh_token"]
