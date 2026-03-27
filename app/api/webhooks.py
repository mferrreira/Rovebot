from __future__ import annotations

from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException

from app.domain.pipeline import EmailPipeline
from app.models.webhook import GmailWebhookPayload, PubSubPayload
from app.settings import Settings, get_settings

router = APIRouter()


@lru_cache(maxsize=1)
def _get_pipeline() -> EmailPipeline:
    return EmailPipeline(get_settings())


@router.post("/webhooks/gmail")
def gmail_webhook(
    payload: GmailWebhookPayload,
    x_rovebot_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if x_rovebot_token != settings.gmail_webhook_token:
        raise HTTPException(status_code=401, detail="invalid gmail webhook token")
    return _get_pipeline().run(payload.message_id)


@router.post("/webhooks/gmail/pubsub", status_code=202)
def gmail_pubsub(
    payload: PubSubPayload,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.pubsub_skip_auth and not _verify_pubsub_token(authorization, settings.pubsub_audience):
        raise HTTPException(status_code=401, detail="invalid pubsub token")
    data = payload.decode_data()
    history_id = str(data["historyId"])
    results = _get_pipeline().process_new_emails(history_id)
    return {"processed": len(results)}


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

@router.post("/webhooks/cron/poll")
def cron_poll(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Triggered by Cloud Scheduler. Wait synchronously so Cloud Run doesn't throttle."""
    if not authorization or authorization.removeprefix("Bearer ") != settings.cron_token:
        raise HTTPException(status_code=401, detail="invalid cron token")
    
    results = _get_pipeline().poll()
    return {"processed": len(results)}
