from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.services.pipeline import EmailPipeline
from app.settings import Settings, get_settings


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


app = FastAPI(title="Rovebot v0")


@lru_cache(maxsize=1)
def get_pipeline() -> EmailPipeline:
    return EmailPipeline(get_settings())


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"status": "ok", "env": settings.env, "time": datetime.now(timezone.utc).isoformat()}


def _verify_pubsub_token(authorization: str | None, audience: str) -> bool:
    if not authorization or not authorization.startswith("Bearer ") or not audience:
        return False
    token = authorization.removeprefix("Bearer ")
    try:
        response = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": token},
            timeout=5.0,
        )
        data = response.json()
        return response.status_code == 200 and data.get("aud") == audience
    except Exception:
        return False


@app.post("/webhooks/gmail")
def gmail_webhook(
    payload: GmailWebhookPayload,
    x_rovebot_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    pipeline: EmailPipeline = Depends(get_pipeline),
) -> dict[str, object]:
    if x_rovebot_token != settings.gmail_webhook_token:
        raise HTTPException(status_code=401, detail="invalid gmail webhook token")
    return pipeline.run(payload.message_id)


@app.post("/webhooks/gmail/pubsub", status_code=202)
def gmail_pubsub(
    payload: PubSubPayload,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    pipeline: EmailPipeline = Depends(get_pipeline),
) -> dict[str, object]:
    if not _verify_pubsub_token(authorization, settings.pubsub_audience):
        raise HTTPException(status_code=401, detail="invalid pubsub token")
    data = payload.decode_data()
    history_id = str(data["historyId"])
    message_ids = pipeline.gmail.fetch_new_message_ids(history_id)
    results = [pipeline.run(message_id) for message_id in message_ids]
    return {"processed": len(results)}
