from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.webhooks import _get_pipeline
from app.settings import Settings, get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhooks/slack/actions")
async def slack_actions(
    request: Request,
    settings: Settings = Depends(get_settings)
) -> JSONResponse:
    raw_body = await request.body()
    logger.info("slack_actions — received request")

    if settings.slack_signing_secret:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not _verify_signature(raw_body, timestamp, signature, settings.slack_signing_secret):
            raise HTTPException(status_code=401, detail="invalid slack signature")

    form = parse_qs(raw_body.decode())
    payload_str = form.get("payload", [None])[0]
    if not payload_str:
        raise HTTPException(status_code=400, detail="missing payload")

    data = json.loads(payload_str)
    event_type = data.get("type")
    logger.info("slack_actions — event_type=%s", event_type)
    try:
        if event_type == "block_actions":
            actions = data.get("actions", [])
            if not actions:
                logger.warning("slack_actions — block_actions without actions payload")
                return JSONResponse({})
            action_id = actions[0].get("action_id")
            message = data.get("message", {})
            slack_ts = message.get("ts", "")
            channel = data.get("channel", {}).get("id", "")
            blocks = message.get("blocks", [])
            user_name = data.get("user", {}).get("name", "unknown")
            trigger_id = data.get("trigger_id", "")
            pipeline = _get_pipeline()
            logger.info(
                "slack_actions — action_id=%s ts=%s channel=%s trigger=%s",
                action_id,
                slack_ts,
                channel,
                bool(trigger_id),
            )

            if action_id == "send_draft":
                _dispatch_background(pipeline.handle_send, slack_ts, channel, blocks, user_name)
            elif action_id == "edit_draft":
                _dispatch_background(pipeline.handle_edit_open, slack_ts, trigger_id)

        elif event_type == "view_submission":
            view = data.get("view", {})
            if view.get("callback_id") == "edit_draft_submit":
                private = json.loads(view.get("private_metadata", "{}"))
                slack_ts = private.get("ts", "")
                channel = private.get("channel", "")
                state = view.get("state", {}).get("values", {})
                edited_text = state.get("draft_text", {}).get("draft_input", {}).get("value", "")
                user_name = data.get("user", {}).get("name", "unknown")
                pipeline = _get_pipeline()
                logger.info("slack_actions — view_submission ts=%s channel=%s", slack_ts, channel)
                _dispatch_background(
                    pipeline.handle_edit_submit, slack_ts, channel, edited_text, user_name
                )
    except Exception:
        logger.exception("slack_actions — handler failed")

    return JSONResponse({})


def _dispatch_background(func, *args) -> None:
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, func, *args)


def _verify_signature(body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning("slack signature — timestamp too old")
            return False
        sig_base = f"v0:{timestamp}:{body.decode()}"
        computed = "v0=" + hmac.new(secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception:
        logger.exception("slack signature verification failed")
        return False
