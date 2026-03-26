from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator

from app.integrations.llm import AnthropicLLMClient
from app.models.email import Email

logger = logging.getLogger(__name__)

CATEGORIES = (
    "product_question",
    "complaint",
    "shipping_issue",
    "partnership",
    "refund",
    "legal",
    "other",
    "others",
)
ATTENTION_CATEGORIES = frozenset({"complaint", "refund", "legal"})
PARTNERSHIP_TIERS = frozenset({"exceptional", "high", "medium", "low", "spam"})


@dataclass(slots=True)
class ClassificationResult:
    category: str
    needs_attention: bool
    attention_reason: str
    score: int | None = None
    partnership_tier: str | None = None


class _ClassificationPayload(BaseModel):
    category: Literal[
        "product_question",
        "complaint",
        "shipping_issue",
        "partnership",
        "refund",
        "legal",
        "other",
        "others",
    ]
    needs_attention: bool
    attention_reason: str
    score: int | None = None
    partnership_tier: Literal["exceptional", "high", "medium", "low", "spam"] | None = None

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("score must be between 0 and 100")
        return v


def classify(email: Email, client: AnthropicLLMClient, system_prompt: str) -> ClassificationResult:
    user_message = json.dumps(
        {
            "from": email.sender,
            "subject": email.subject,
            "body": email.body,
            "thread_history": email.thread_history,
        },
        ensure_ascii=True,
    )
    raw = client.complete(system_prompt, user_message, max_tokens=512)
    return _parse(raw)


def _parse(raw: str) -> ClassificationResult:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        logger.error("_parse — no JSON found in LLM response: %r", raw)
    candidate = match.group(0) if match else raw

    try:
        data = json.loads(candidate)
        payload = _ClassificationPayload.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("_parse — validation failed: %s | raw=%r", exc, raw)
        raise ValueError("invalid classification response from llm") from exc

    if payload.category in ATTENTION_CATEGORIES and not payload.needs_attention:
        logger.error("_parse — business rule violation: %s must have needs_attention=true", payload.category)
        raise ValueError("sensitive category must require attention")

    if payload.category == "partnership":
        if payload.score is None or payload.partnership_tier is None:
            logger.error("_parse — partnership missing score or tier: score=%s tier=%s",
                         payload.score, payload.partnership_tier)
            raise ValueError("partnership emails must include score and partnership_tier")
        if payload.partnership_tier in ("exceptional", "high") and not payload.needs_attention:
            logger.error("_parse — business rule violation: tier=%s must have needs_attention=true",
                         payload.partnership_tier)
            raise ValueError("exceptional and high partnership tiers must require attention")

    if not payload.needs_attention and payload.attention_reason.strip():
        logger.error("_parse — attention_reason set but needs_attention=false")
        raise ValueError("attention_reason must be empty when no attention is required")

    if payload.needs_attention and not payload.attention_reason.strip():
        logger.error("_parse — needs_attention=true but attention_reason is empty")
        raise ValueError("attention_reason is required when attention is needed")

    return ClassificationResult(
        category=payload.category.strip(),
        needs_attention=payload.needs_attention,
        attention_reason=payload.attention_reason.strip(),
        score=payload.score,
        partnership_tier=payload.partnership_tier,
    )
