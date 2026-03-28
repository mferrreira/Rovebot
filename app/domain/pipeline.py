from __future__ import annotations

import logging
import re
from pathlib import Path

from app.domain.classification import ClassificationResult, classify
from app.domain.draft_store import DraftContext, DraftStore
from app.domain.drafting import draft
from app.domain.guardrails import check_draft
from app.domain.learning import extract_and_append
from app.integrations.gmail import GmailApiClient
from app.integrations.llm import AnthropicLLMClient
from app.integrations.slack import SlackApiClient
from app.models.draft import DraftResult
from app.models.email import Email
from app.settings import Settings

logger = logging.getLogger(__name__)


def _label_for(classification: ClassificationResult) -> str:
    if classification.category == "partnership" and classification.partnership_tier:
        tier = classification.partnership_tier.capitalize()
        return f"Rovebot/Partnership/{tier}"
    label = classification.category.replace("_", " ").title()
    return f"Rovebot/{label}"


class EmailPipeline:
    def __init__(self, settings: Settings, gmail=None, classify_llm=None, draft_llm=None, slack=None):
        self.settings = settings
        classify_base = Path("prompts/classify.md").read_text(encoding="utf-8")
        _rubric = self._load_optional(settings.knowledge_dir / "rubric.md")
        self.classify_prompt = f"{classify_base}\n\n{_rubric}".strip() if _rubric else classify_base
        draft_base = Path("prompts/draft.md").read_text(encoding="utf-8")
        sender_line = f"Sender name (use this to sign replies): {settings.sender_name}" if settings.sender_name else ""
        self.draft_prompt = f"{draft_base}\n\n{sender_line}".strip() if sender_line else draft_base
        self.style_guide = self._load_optional(settings.knowledge_dir / "STYLEGUIDE.md")
        self.learning_path = settings.learning_file
        self.learning = self._load_optional(self.learning_path)
        self.gmail = gmail or self._build_gmail_client()
        self.classify_llm = classify_llm or self._build_classify_llm_client()
        self.draft_llm = draft_llm or self._build_draft_llm_client()
        self.slack = slack or self._build_slack_client()
        self.draft_store = DraftStore(settings.draft_store_file)
        logger.info("EmailPipeline ready")

    def run(self, message_id: str) -> dict[str, object]:
        logger.info("run — message_id=%s", message_id)

        email = self._fetch_and_clean(message_id)
        logger.info("email from=%r subject=%r", email.sender, email.subject)

        # ── Classify (with fallback) ──────────────────────────────────────────
        try:
            classification = classify(email, self.classify_llm, self.classify_prompt)
            logger.info("classified — category=%s attention=%s tier=%s",
                        classification.category, classification.needs_attention,
                        classification.partnership_tier)
        except Exception:
            logger.exception("classification failed")
            self.slack.send_pipeline_error(email, "Classification failed — please review manually.")
            return {"message_id": email.message_id, "error": "classification_failed"}

        # ── Automated / spam short-circuits ──────────────────────────────────
        if classification.category == "others":
            self.gmail.apply_label(email.message_id, _label_for(classification))
            logger.info("others — labeled and logged, no further action")
            return {
                "message_id": email.message_id,
                "category": "others",
                "needs_attention": False,
                "attention_reason": "",
                "draft": None,
                "score": None,
                "partnership_tier": None,
                "gmail_draft_id": None,
                "slack": None,
            }

        if classification.partnership_tier == "spam":
            logger.info("partnership spam — ignoring entirely (score=%s)", classification.score)
            return {
                "message_id": email.message_id,
                "category": "partnership",
                "needs_attention": False,
                "attention_reason": "",
                "draft": None,
                "score": classification.score,
                "partnership_tier": "spam",
                "gmail_draft_id": None,
                "slack": None,
            }

        self.gmail.apply_label(email.message_id, _label_for(classification))

        # ── Draft (with fallback + guardrails) ────────────────────────────────
        draft_text: str | None = None
        guardrail_warnings: list[str] = []
        try:
            draft_text = draft(email, classification, self.draft_llm, self.draft_prompt,
                               self.style_guide, self.learning)
            if draft_text:
                guard = check_draft(draft_text)
                if not guard.passed:
                    logger.warning("draft guardrail warnings: %s", guard.warnings)
                    guardrail_warnings = guard.warnings
        except Exception:
            logger.exception("draft generation failed")
            guardrail_warnings = ["Draft generation failed — respond manually."]

        # ── Save Gmail draft (with fallback) ──────────────────────────────────
        gmail_draft_id: str | None = None
        if draft_text:
            try:
                gmail_draft_id = self.gmail.create_draft(
                    email.sender, email.subject, draft_text, email.thread_id
                )
                logger.info("Gmail draft created id=%s", gmail_draft_id)
            except Exception:
                logger.exception("gmail draft creation failed — draft will be shown inline only")
                self.slack.send_pipeline_error(email, "Gmail draft creation failed — draft shown in Slack only.")

        result = DraftResult(
            category=classification.category,
            needs_attention=classification.needs_attention,
            attention_reason=classification.attention_reason,
            draft=draft_text,
            score=classification.score,
            partnership_tier=classification.partnership_tier,
            gmail_draft_id=gmail_draft_id,
            guardrail_warnings=guardrail_warnings,
        )

        # ── Slack notification ────────────────────────────────────────────────
        slack_result: dict[str, str] | None = None
        try:
            slack_result = self.slack.send(email, result)
            logger.info("Slack notified")
        except Exception:
            logger.exception("slack notification failed")

        # ── Save context for interactive actions ──────────────────────────────
        if slack_result and draft_text:
            self.draft_store.save(
                slack_result["ts"],
                DraftContext(
                    gmail_draft_id=gmail_draft_id,
                    original_draft=draft_text,
                    email_sender=email.sender,
                    email_subject=email.subject,
                    thread_id=email.thread_id,
                    channel=slack_result["channel"],
                ),
            )

        return {
            "message_id": email.message_id,
            "category": result.category,
            "needs_attention": result.needs_attention,
            "attention_reason": result.attention_reason,
            "draft": result.draft,
            "score": result.score,
            "partnership_tier": result.partnership_tier,
            "gmail_draft_id": result.gmail_draft_id,
            "guardrail_warnings": result.guardrail_warnings,
            "slack": slack_result,
        }

    def handle_send(self, slack_ts: str, channel: str, blocks: list[dict], user_name: str) -> None:
        ctx = self.draft_store.get(slack_ts)
        if not ctx:
            logger.warning("handle_send — no context for ts=%s", slack_ts)
            return
        if not ctx.gmail_draft_id:
            logger.warning("handle_send — no gmail_draft_id for ts=%s", slack_ts)
            return
        try:
            self.gmail.send_draft(ctx.gmail_draft_id)
            logger.info("draft sent id=%s", ctx.gmail_draft_id)
        except Exception:
            logger.exception("handle_send — gmail send failed")
            return
        try:
            self.slack.update_message(
                channel,
                slack_ts,
                _build_sent_status_blocks(blocks, user_name),
                f"Draft sent by {user_name}",
            )
        except Exception:
            logger.exception("handle_send — slack update failed")

    def handle_edit_open(self, slack_ts: str, trigger_id: str) -> None:
        ctx = self.draft_store.get(slack_ts)
        if not ctx:
            logger.warning("handle_edit_open — no context for ts=%s", slack_ts)
            return
        import json as _json
        private_metadata = _json.dumps({"ts": slack_ts, "channel": ctx.channel})
        try:
            self.slack.open_modal(trigger_id, ctx.original_draft, private_metadata)
        except Exception:
            logger.exception("handle_edit_open — open_modal failed")

    def handle_edit_submit(self, slack_ts: str, channel: str, edited_text: str, user_name: str) -> None:
        ctx = self.draft_store.get(slack_ts)
        if not ctx:
            logger.warning("handle_edit_submit — no context for ts=%s", slack_ts)
            return
        original = ctx.original_draft
        if ctx.gmail_draft_id:
            try:
                self.gmail.update_draft(
                    ctx.gmail_draft_id, ctx.email_sender, ctx.email_subject,
                    edited_text, ctx.thread_id,
                )
                logger.info("draft updated id=%s", ctx.gmail_draft_id)
            except Exception:
                logger.exception("handle_edit_submit — gmail update failed")
        extract_and_append(original, edited_text, self.draft_llm, self.learning_path)
        self.learning = self._load_optional(self.learning_path)
        self.draft_store.update_original(slack_ts, edited_text)
        try:
            self.slack.update_message(
                channel, slack_ts,
                _build_edited_status_blocks(edited_text, user_name),
                f"Draft edited by {user_name}",
            )
        except Exception:
            logger.exception("handle_edit_submit — slack update failed")

    def poll(self) -> list[dict[str, object]]:
        saved_id = self._load_history_id()
        if not saved_id:
            self._save_history_id(self.gmail.get_history_id())
            return []
        new_id = self.gmail.get_history_id()
        message_ids = list(dict.fromkeys(self.gmail.fetch_new_message_ids(saved_id)))
        if message_ids:
            logger.info("poll — found %d new message(s)", len(message_ids))
        self._save_history_id(new_id)
        results = []
        for mid in message_ids:
            try:
                results.append(self.run(mid))
            except Exception as e:
                logger.warning("poll — skipping message %s: %s", mid, e)
        return results

    def process_new_emails(self, notification_history_id: str) -> list[dict[str, object]]:
        start_id = self._load_history_id() or notification_history_id
        message_ids = self.gmail.fetch_new_message_ids(start_id)
        logger.info("webhook — %d message(s) to process", len(message_ids))
        results = [self.run(mid) for mid in message_ids]
        self._save_history_id(notification_history_id)
        return results

    def _fetch_and_clean(self, message_id: str) -> Email:
        email = self.gmail.fetch_email(message_id)
        return Email(
            message_id=email.message_id,
            thread_id=email.thread_id,
            sender=email.sender,
            subject=email.subject.strip(),
            body=self._clean_text(email.body),
            thread_history=[self._clean_text(h) for h in email.thread_history if h.strip()],
            received_at=email.received_at,
        )

    def _load_history_id(self) -> str | None:
        path = self.settings.history_id_file
        return path.read_text().strip() if path.exists() else None

    def _save_history_id(self, history_id: str) -> None:
        self.settings.history_id_file.write_text(history_id)

    def _build_gmail_client(self) -> GmailApiClient:
        if not self.settings.gmail_access_token and not self.settings.gmail_refresh_token:
            raise ValueError("Run 'uv run rovebot setup' to authorize Gmail access.")
        return GmailApiClient(
            self.settings.gmail_api_base_url,
            access_token=self.settings.gmail_access_token or None,
            client_id=self.settings.gmail_client_id,
            client_secret=self.settings.gmail_client_secret,
            refresh_token=self.settings.gmail_refresh_token,
            timeout=self.settings.gmail_timeout,
        )

    def _build_classify_llm_client(self) -> AnthropicLLMClient:
        if not self.settings.anthropic_api_key:
            raise ValueError("ROVEBOT_ANTHROPIC_API_KEY is required")
        return AnthropicLLMClient(
            self.settings.anthropic_api_key,
            self.settings.classify_model,
            self.settings.anthropic_base_url,
        )

    def _build_draft_llm_client(self) -> AnthropicLLMClient:
        if not self.settings.anthropic_api_key:
            raise ValueError("ROVEBOT_ANTHROPIC_API_KEY is required")
        return AnthropicLLMClient(
            self.settings.anthropic_api_key,
            self.settings.draft_model,
            self.settings.anthropic_base_url,
        )

    def _build_slack_client(self) -> SlackApiClient:
        if not self.settings.slack_bot_token:
            raise ValueError("ROVEBOT_SLACK_BOT_TOKEN is required")
        return SlackApiClient(
            self.settings.slack_api_url,
            self.settings.slack_bot_token,
            self.settings.slack_channel,
            update_url=self.settings.slack_update_url,
            views_url=self.settings.slack_views_url,
        )

    @staticmethod
    def _load_optional(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()[:4000]


def _build_edited_status_blocks(edited_text: str, user_name: str) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Draft reply (edited by @{user_name}):*\n```{edited_text}```"},
        },
        {
            "type": "actions",
            "block_id": "draft_actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "send_draft",
                    "text": {"type": "plain_text", "text": "Send Draft"},
                    "style": "primary",
                },
                {
                    "type": "button",
                    "action_id": "edit_draft",
                    "text": {"type": "plain_text", "text": "Edit Draft"},
                },
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"✏️ Edited by @{user_name}"}],
        },
    ]


def _build_sent_status_blocks(blocks: list[dict], user_name: str) -> list[dict]:
    updated = [b for b in blocks if b.get("type") != "actions"]
    updated.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"✅ Sent by @{user_name}"}],
    })
    return updated
