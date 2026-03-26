from __future__ import annotations

import logging

import httpx

from app.models.draft import DraftResult
from app.models.email import Email

logger = logging.getLogger(__name__)


class SlackApiClient:
    def __init__(
        self,
        api_url: str,
        bot_token: str,
        channel: str,
        timeout: float = 10.0,
        update_url: str = "https://slack.com/api/chat.update",
        views_url: str = "https://slack.com/api/views.open",
    ):
        self.api_url = api_url
        self.bot_token = bot_token
        self.channel = channel
        self.timeout = timeout
        self.update_url = update_url
        self.views_url = views_url

    def send(self, email: Email, result: DraftResult) -> dict[str, str]:
        blocks = self._build_blocks(email, result)
        fallback = f"New email from {email.sender} — {email.subject} [{result.category}]"
        logger.info("[SLACK] %s", fallback)
        data = self._post(self.api_url, {"channel": self.channel, "text": fallback, "blocks": blocks})
        return {"channel": data["channel"], "ts": data["ts"]}

    def send_pipeline_error(self, email: Email, error: str) -> None:
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Pipeline error* — {error}\n*From:* {email.sender}\n*Subject:* {email.subject}",
                },
            }
        ]
        try:
            self._post(self.api_url, {"channel": self.channel, "text": error, "blocks": blocks})
        except Exception:
            logger.exception("send_pipeline_error — failed to notify Slack")

    def update_message(self, channel: str, ts: str, blocks: list[dict], fallback: str) -> None:
        self._post(self.update_url, {"channel": channel, "ts": ts, "text": fallback, "blocks": blocks})

    def open_modal(self, trigger_id: str, draft_text: str, private_metadata: str) -> None:
        modal = {
            "type": "modal",
            "callback_id": "edit_draft_submit",
            "private_metadata": private_metadata,
            "title": {"type": "plain_text", "text": "Edit Draft"},
            "submit": {"type": "plain_text", "text": "Save & Update"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "draft_text",
                    "label": {"type": "plain_text", "text": "Draft reply"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "draft_input",
                        "multiline": True,
                        "initial_value": draft_text,
                    },
                }
            ],
        }
        self._post(self.views_url, {"trigger_id": trigger_id, "view": modal})

    def _build_blocks(self, email: Email, result: DraftResult) -> list[dict]:
        category_label = result.category.replace("_", " ").title()
        attention_text = "*Yes* ⚠️" if result.needs_attention else "No"

        blocks: list[dict] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*New email needs review*\n"
                        f"*From:* {email.sender}\n"
                        f"*Subject:* {email.subject}"
                    ),
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Category:*\n{category_label}"},
                    {"type": "mrkdwn", "text": f"*Needs attention:*\n{attention_text}"},
                ],
            },
        ]

        if result.attention_reason:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Attention reason:* {result.attention_reason}"},
            })

        if result.partnership_tier:
            score_str = f"{result.score}/100" if result.score is not None else "—"
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Partnership tier:*\n{result.partnership_tier.capitalize()}"},
                    {"type": "mrkdwn", "text": f"*Score:*\n{score_str}"},
                ],
            })

        if result.guardrail_warnings:
            warning_lines = "\n".join(f"• {w}" for w in result.guardrail_warnings)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: *Draft warnings:*\n{warning_lines}"},
            })

        if result.draft:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Draft reply:*\n```{result.draft}```"},
            })
            if result.gmail_draft_id:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"Gmail draft ID: `{result.gmail_draft_id}`"}],
                })
            blocks.append({
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
            })
        elif result.gmail_draft_id:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Gmail draft saved — ID: `{result.gmail_draft_id}`"}],
            })
        elif result.partnership_tier in ("exceptional", "high"):
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No auto-reply drafted — respond manually._"},
            })

        return blocks

    def _post(self, url: str, body: dict) -> dict:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self.bot_token}"},
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack api error: {data.get('error', data)}")
        return data
