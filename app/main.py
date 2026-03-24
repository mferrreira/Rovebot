from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException

from app.models import GmailWebhookPayload, PubSubPayload
from app.services.pipeline import EmailPipeline
from app.settings import Settings, get_settings


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
    if not settings.pubsub_skip_auth and not _verify_pubsub_token(authorization, settings.pubsub_audience):
        raise HTTPException(status_code=401, detail="invalid pubsub token")
    data = payload.decode_data()
    history_id = str(data["historyId"])
    results = pipeline.process_new_emails(history_id)
    return {"processed": len(results)}


def main() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
