from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from pathlib import Path

_MAX_ENTRIES = 500


@dataclass
class DraftContext:
    gmail_draft_id: str | None
    original_draft: str
    email_sender: str
    email_subject: str
    thread_id: str
    channel: str


class DraftStore:
    def __init__(self, path: Path):
        self._path = path

    def save(self, slack_ts: str, context: DraftContext) -> None:
        data = self._load()
        data[slack_ts] = asdict(context)
        if len(data) > _MAX_ENTRIES:
            for key in list(data.keys())[: len(data) - _MAX_ENTRIES]:
                del data[key]
        self._dump(data)

    def get(self, slack_ts: str) -> DraftContext | None:
        entry = self._load().get(slack_ts)
        return DraftContext(**entry) if entry else None

    def update_original(self, slack_ts: str, new_draft: str) -> None:
        data = self._load()
        if slack_ts in data:
            data[slack_ts]["original_draft"] = new_draft
            self._dump(data)

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _dump(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2))
