from __future__ import annotations

import base64
import json

from pydantic import BaseModel

class GmailWebhookPayload(BaseModel):
    message_id: str

class PubSubMessage(BaseModel):
    data: str
    messageId: str

class PubSubPayload(BaseModel):
    message: PubSubMessage
    subscription: str

    def decode_data(self) -> dict:
        padded = self.message.data + "=" * (-len(self.message.data) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))