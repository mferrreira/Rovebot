from __future__ import annotations

import json

from app.domain.classification import ClassificationResult
from app.integrations.llm import AnthropicLLMClient
from app.models.email import Email

_NO_DRAFT_TIERS = frozenset({"exceptional", "high", "spam"})


def draft(
    email: Email,
    classification: ClassificationResult,
    client: AnthropicLLMClient,
    system_prompt: str,
    style_guide: str,
    learning: str = "",
) -> str | None:
    if classification.partnership_tier in _NO_DRAFT_TIERS:
        return None

    parts = [system_prompt]
    if style_guide:
        parts.append(style_guide)
    if learning:
        parts.append(f"Style learnings from past edits:\n{learning}")
    system = "\n\n".join(parts)

    user_message = json.dumps(
        {
            "from": email.sender,
            "subject": email.subject,
            "body": email.body,
            "thread_history": email.thread_history,
            "category": classification.category,
            "needs_attention": classification.needs_attention,
            "partnership_tier": classification.partnership_tier,
        },
        ensure_ascii=True,
    )
    return client.complete(system, user_message, max_tokens=700)
