from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DraftResult:
    category: str
    needs_attention: bool
    attention_reason: str
    draft: str | None
    score: int | None = None
    partnership_tier: str | None = None
    gmail_draft_id: str | None = None
    guardrail_warnings: list[str] = field(default_factory=list)
