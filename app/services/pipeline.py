from __future__ import annotations

import re
from pathlib import Path

from app.integrations.gmail import GmailApiClient, GmailEmail
from app.integrations.llm import AnthropicLLMClient
from app.integrations.slack import SlackApiClient
from app.settings import Settings

class EmailPipeline:
    def __init__(self, settings: Settings, gmail=None, llm=None, slack=None):
        self.settings = settings
        self.gmail = gmail or self._build_gmail_client()
        self.llm = llm or self._build_llm_client()
        self.slack = slack or self._build_slack_client()

    def run(self, message_id: str) -> dict[str, object]:
        email = self.gmail.fetch_email(message_id)
        clean_email = GmailEmail(
            message_id=email.message_id,
            thread_id=email.thread_id,
            sender=email.sender,
            subject=email.subject.strip(),
            body=self._clean_text(email.body),
            thread_history=[self._clean_text(item) for item in email.thread_history if item.strip()],
            received_at=email.received_at,
        )
        knowledge = self._load_knowledge()
        draft = self.llm.generate(clean_email, knowledge)
        slack_result = self.slack.send(clean_email, draft)
        return {
            "message_id": clean_email.message_id,
            "category": draft.category,
            "needs_attention": draft.needs_attention,
            "attention_reason": draft.attention_reason,
            "draft": draft.draft,
            "slack": slack_result,
        }

    def _load_knowledge(self) -> str:
        path = Path(self.settings.knowledge_dir) / "style_guide.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")[:4000]

    def _build_gmail_client(self):
        if not self.settings.gmail_access_token:
            raise ValueError("ROVEBOT_GMAIL_ACCESS_TOKEN is required")
        return GmailApiClient(self.settings.gmail_api_base_url, self.settings.gmail_access_token)

    def _build_llm_client(self):
        if not self.settings.anthropic_api_key:
            raise ValueError("ROVEBOT_ANTHROPIC_API_KEY is required")
        return AnthropicLLMClient(self.settings.anthropic_api_key, self.settings.llm_model, self.settings.anthropic_base_url)

    def _build_slack_client(self):
        if not self.settings.slack_bot_token:
            raise ValueError("ROVEBOT_SLACK_BOT_TOKEN is required")
        return SlackApiClient(self.settings.slack_api_url, self.settings.slack_bot_token, self.settings.slack_channel)

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()[:4000]
