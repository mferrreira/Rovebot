from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Email:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    thread_history: list[str]
    received_at: datetime
