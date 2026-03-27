from __future__ import annotations
import logging
from pathlib import Path

from app.integrations.llm import AnthropicLLMClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You extract email writing style learnings from human edits. "
    "Given an original AI-generated draft and the human-edited version, output 1-2 concise bullet points "
    "describing what the human prefers differently. "
    "Focus on tone, structure, formality, greeting style, or specific content choices. "
    "Output only the bullet points starting with '-', no preamble."
)


def extract_and_append(original: str, edited: str, client: AnthropicLLMClient, learning_path: Path) -> None:
    if original.strip() == edited.strip():
        return
    user_msg = f"<original>\n{original}\n</original>\n\n<edited>\n{edited}\n</edited>"
    try:
        bullets = client.complete(_SYSTEM, user_msg, max_tokens=200).strip()
    except Exception:
        logger.exception("learning — LLM call failed")
        return
    if not bullets:
        return
    existing = learning_path.read_text(encoding="utf-8") if learning_path.exists() else ""
    sep = "\n\n" if existing.strip() else ""
    learning_path.parent.mkdir(parents=True, exist_ok=True)
    learning_path.write_text(existing + sep + bullets + "\n", encoding="utf-8")
    logger.info("learning — new bullets appended to %s", learning_path)
