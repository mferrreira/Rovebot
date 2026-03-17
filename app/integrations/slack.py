from __future__ import annotations

import httpx

from app.integrations.gmail import GmailEmail
from app.integrations.llm import DraftResult


class SlackApiClient:
    def __init__(self, api_url: str, bot_token: str, channel: str, timeout: float = 10.0):
        self.api_url = api_url
        self.bot_token = bot_token
        self.channel = channel
        self.timeout = timeout

    def send(self, email: GmailEmail, draft: DraftResult) -> dict[str, str]:
        text = (
            f"New email from {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Category: {draft.category}\n"
            f"Needs attention: {'yes' if draft.needs_attention else 'no'}\n"
            f"Attention reason: {draft.attention_reason or '-'}\n\n"
            f"Draft:\n{draft.draft}"
        )
        response = httpx.post(
            self.api_url,
            headers={"Authorization": f"Bearer {self.bot_token}"},
            json={"channel": self.channel, "text": text},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack post failed: {data}")
        return {"channel": data["channel"], "ts": data["ts"]}
