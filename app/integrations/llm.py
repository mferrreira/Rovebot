from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations.gmail import GmailEmail


ALLOWED_CATEGORIES = (
    "product_question",
    "complaint",
    "shipping_issue",
    "partnership",
    "refund",
    "legal",
    "other",
)

ATTENTION_CATEGORIES = ("complaint", "refund", "legal")


class DraftPayload(BaseModel):
    category: Literal[
        "product_question",
        "complaint",
        "shipping_issue",
        "partnership",
        "refund",
        "legal",
        "other",
    ]
    needs_attention: bool
    attention_reason: str
    draft: str


@dataclass(slots=True)
class DraftResult:
    category: str
    needs_attention: bool
    attention_reason: str
    draft: str


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str, base_url: str, system_prompt: str, timeout: float = 20.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.timeout = timeout

    def generate(self, email: GmailEmail, knowledge: str) -> DraftResult:
        payload = {
            "email": {
                "from": email.sender,
                "subject": email.subject,
                "body": email.body,
                "thread_history": email.thread_history,
            },
            "knowledge": knowledge,
        }
        response = httpx.post(
            self.base_url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 700,
                "system": self.system_prompt,
                "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=True)}],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        text = "\n".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return parse_draft_result(text)


def parse_draft_result(raw: str) -> DraftResult:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    candidate = match.group(0) if match else raw
    try:
        data = json.loads(candidate)
        parsed = DraftPayload.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("invalid draft payload from llm") from exc
    if parsed.category in ATTENTION_CATEGORIES and not parsed.needs_attention:
        raise ValueError("invalid draft payload from llm: sensitive category must require attention")
    if not parsed.needs_attention and parsed.attention_reason.strip():
        raise ValueError("invalid draft payload from llm: attention_reason must be empty when no attention is required")
    if parsed.needs_attention and not parsed.attention_reason.strip():
        raise ValueError("invalid draft payload from llm: attention_reason is required when attention is needed")
    return DraftResult(
        category=parsed.category.strip(),
        needs_attention=parsed.needs_attention,
        attention_reason=parsed.attention_reason.strip(),
        draft=parsed.draft.strip(),
    )
