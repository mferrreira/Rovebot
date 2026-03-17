from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_pipeline
from app.integrations.gmail import GmailEmail
from app.integrations.llm import DraftResult
from app.services.pipeline import EmailPipeline
from app.settings import Settings


class StubGmailClient:
    def fetch_email(self, message_id: str) -> GmailEmail:
        return GmailEmail(
            message_id=message_id,
            thread_id="thread-1",
            sender="client@example.com",
            subject="Need help with enterprise pricing",
            body="Hi team, can you explain enterprise pricing and onboarding timelines?",
            thread_history=[
                "Customer already asked about contract terms.",
                "They also want to understand onboarding timing.",
            ],
            received_at=datetime.now(timezone.utc),
        )

    def fetch_new_message_ids(self, history_id: str) -> list[str]:
        if history_id == "12345":
            return ["msg-1", "msg-2"]
        return []


class StubLLMClient:
    def generate(self, email: GmailEmail, knowledge: str) -> DraftResult:
        return DraftResult(
            category="product_question",
            needs_attention=False,
            attention_reason="",
            draft="Thanks for your message. I am reviewing the pricing details and will follow up shortly.",
        )


@dataclass
class StubSlackClient:
    posts: list[dict[str, str]]

    def send(self, email: GmailEmail, draft: DraftResult) -> dict[str, str]:
        message = {
            "channel": "#email-review",
            "subject": email.subject,
            "sender": email.sender,
            "category": draft.category,
            "needs_attention": "yes" if draft.needs_attention else "no",
            "attention_reason": draft.attention_reason,
            "draft": draft.draft,
        }
        self.posts.append(message)
        return message


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "style_guide.md").write_text(
        "Keep the tone calm, concise, and direct. Never overpromise. Lead with empathy when needed.",
        encoding="utf-8",
    )
    return Settings(
        env="test",
        knowledge_dir=knowledge_dir,
        gmail_webhook_token="test-gmail-token",
        pubsub_audience="https://rovebot.example.com/webhooks/gmail/pubsub",
        slack_channel="#email-review",
    )


@pytest.fixture()
def pipeline(settings: Settings) -> EmailPipeline:
    return EmailPipeline(
        settings,
        gmail=StubGmailClient(),
        llm=StubLLMClient(),
        slack=StubSlackClient(posts=[]),
    )


@pytest.fixture()
def client(pipeline: EmailPipeline):
    from app.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: pipeline.settings
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
