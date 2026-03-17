from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import Message

import httpx

@dataclass(slots=True)
class GmailEmail:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    thread_history: list[str]
    received_at: datetime


class GmailApiClient:
    def __init__(self, api_base_url: str, access_token: str, timeout: float = 10.0):
        self.api_base_url = api_base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout

    def fetch_email(self, message_id: str) -> GmailEmail:
        message_response = self._get(f"/users/me/messages/{message_id}?format=raw")
        message_payload = message_response.json()
        raw_bytes = base64.urlsafe_b64decode(message_payload["raw"])
        mime_message = message_from_bytes(raw_bytes)
        thread_id = message_payload.get("threadId", message_id)
        thread_history = self._fetch_thread(thread_id)
        return GmailEmail(
            message_id=message_id,
            thread_id=thread_id,
            sender=mime_message.get("From", ""),
            subject=mime_message.get("Subject", ""),
            body=self._extract_body(mime_message),
            thread_history=thread_history,
            received_at=datetime.now(timezone.utc),
        )

    def fetch_new_message_ids(self, history_id: str) -> list[str]:
        response = self._get(f"/users/me/history?startHistoryId={history_id}&historyTypes=messageAdded")
        payload = response.json()
        ids: list[str] = []
        for record in payload.get("history", []):
            for added in record.get("messagesAdded", []):
                message = added.get("message", {})
                message_id = message.get("id")
                if message_id:
                    ids.append(message_id)
        return ids

    def _fetch_thread(self, thread_id: str) -> list[str]:
        response = self._get(f"/users/me/threads/{thread_id}?format=metadata")
        payload = response.json()
        items: list[str] = []
        for message in payload.get("messages", []):
            headers = {header["name"].lower(): header["value"] for header in message.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            if sender or subject:
                items.append(f"From {sender}: {subject}")
        return items

    def _get(self, path: str) -> httpx.Response:
        response = httpx.get(
            f"{self.api_base_url}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

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
