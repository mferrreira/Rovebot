from __future__ import annotations
import re
from dataclasses import dataclass, field

@dataclass
class GuardrailResult:
    passed: bool
    warnings: list[str] = field(default_factory=list)

_PLACEHOLDER_RE = re.compile(r'\[[A-Z][A-Z _\-]{2,}\]')
_HEADER_RE = re.compile(r'^(Subject|To|From|Cc|Bcc|Date):', re.MULTILINE)

def check_draft(draft: str) -> GuardrailResult:
    warnings: list[str] = []
    placeholders = _PLACEHOLDER_RE.findall(draft)
    if placeholders:
        warnings.append(f"Unfilled placeholders: {', '.join(placeholders)}")
    stripped = draft.strip()
    if len(stripped) < 20:
        warnings.append(f"Draft too short ({len(stripped)} chars)")
    elif len(draft) > 2000:
        warnings.append(f"Draft very long ({len(draft)} chars) — verify content")
    if _HEADER_RE.search(draft):
        warnings.append("Draft contains email header lines")
    return GuardrailResult(passed=len(warnings) == 0, warnings=warnings)
