from __future__ import annotations

import asyncio
import logging
import logging.config
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI

from app.api import slack_actions, webhooks
from app.domain.pipeline import EmailPipeline
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "app": {"level": "DEBUG", "propagate": True},
        "uvicorn": {"level": "INFO", "propagate": True},
        "uvicorn.access": {"level": "WARNING", "propagate": True},
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.config.dictConfig(_LOGGING_CONFIG)
    settings = get_settings()
    logger.info("Rovebot starting — env=%s polling=%s interval=%ss",
                settings.env, settings.gmail_polling, settings.polling_interval_seconds)
    if settings.gmail_polling:
        task = asyncio.create_task(_polling_loop(settings))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        logger.info("Polling disabled — running in webhook mode only")
        yield


async def _polling_loop(settings: Settings) -> None:
    loop = asyncio.get_event_loop()
    logger.info("Building pipeline for polling...")
    pipeline = EmailPipeline(settings)
    logger.info("Polling loop started — interval=%ss", settings.polling_interval_seconds)
    while True:
        await asyncio.sleep(settings.polling_interval_seconds)
        logger.debug("Polling cycle starting...")
        try:
            results = await loop.run_in_executor(None, pipeline.poll)
            logger.info("Polling cycle done — %d message(s) processed", len(results))
        except Exception:
            logger.exception("Polling cycle failed")


app = FastAPI(title="Rovebot", lifespan=lifespan)
app.include_router(webhooks.router)
app.include_router(slack_actions.router)


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"status": "ok", "env": settings.env, "time": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        _run_setup()
        return
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


def _run_setup() -> None:
    from app.integrations.gmail import run_oauth_flow

    settings = get_settings()
    print("=== Rovebot Setup ===")
    print("Press Enter to keep the current value shown in [brackets].\n")

    # ── [ 1 / 4 ] Anthropic ──────────────────────────────────────────────────
    print("[ 1 / 4 ] Anthropic API Key\n")
    current_key = settings.anthropic_api_key or ""
    hint = f"[{current_key[:12]}...] " if current_key else ""
    api_key = input(f"  Anthropic API key {hint}(sk-ant-...): ").strip()
    if api_key:
        _update_env("ROVEBOT_ANTHROPIC_API_KEY", api_key)
        print("  Saved.\n")
    elif current_key:
        print("  Kept existing key.\n")
    else:
        print("  WARNING: no API key set — LLM calls will fail.\n")

    # ── [ 2 / 4 ] Gmail ──────────────────────────────────────────────────────
    print("[ 2 / 4 ] Gmail OAuth\n")
    print("  Make sure 'http://localhost:8080/callback' is an authorized redirect URI")
    print("  in your Google Cloud Console OAuth app.\n")
    access_token, refresh_token = run_oauth_flow(
        settings.gmail_client_id, settings.gmail_client_secret
    )
    _update_env("ROVEBOT_GMAIL_ACCESS_TOKEN", access_token)
    _update_env("ROVEBOT_GMAIL_REFRESH_TOKEN", refresh_token)
    print("  Gmail tokens saved.\n")

    # ── [ 3 / 4 ] Slack ──────────────────────────────────────────────────────
    print("[ 3 / 4 ] Slack App\n")
    print("  If you haven't created a Slack app yet, follow these steps:\n")
    print("  a) https://api.slack.com/apps → 'Create New App' → 'From scratch'")
    print("     Name it (e.g. Rovebot) and pick your workspace.\n")
    print("  b) 'OAuth & Permissions' → Bot Token Scopes → add:  chat:write\n")
    print("  c) 'Install to Workspace' → copy the Bot User OAuth Token (xoxb-...).\n")
    print("  d) 'Basic Information' → App Credentials → copy the Signing Secret.\n")
    print("  e) 'Interactivity & Shortcuts' → toggle ON.")
    print("     You will set the Request URL after entering your server address below.\n")
    print("  f) In Slack, invite the bot to your channel:  /invite @YourBotName\n")

    bot_token = input("  Slack bot token (xoxb-...): ").strip()
    signing_secret = input("  Slack signing secret: ").strip()
    current_channel = settings.slack_channel
    channel = input(f"  Channel [{current_channel}]: ").strip() or current_channel

    if bot_token:
        _update_env("ROVEBOT_SLACK_BOT_TOKEN", bot_token)
    if signing_secret:
        _update_env("ROVEBOT_SLACK_SIGNING_SECRET", signing_secret)
    _update_env("ROVEBOT_SLACK_CHANNEL", channel)

    server_url = input("\n  Public URL of this server (e.g. https://rovebot.example.com): ").strip().rstrip("/")
    if server_url:
        interactivity_url = f"{server_url}/webhooks/slack/actions"
        print(f"\n  → Set this as the Interactivity Request URL in your Slack app:")
        print(f"    {interactivity_url}\n")
    else:
        print("\n  → Remember to set the Interactivity Request URL in your Slack app:")
        print("    https://YOUR_SERVER/webhooks/slack/actions\n")

    # ── [ 4 / 4 ] Polling ────────────────────────────────────────────────────
    print("[ 4 / 4 ] Gmail Polling\n")
    print("  Polling mode checks Gmail on a background loop (no webhook needed).")
    current_polling = "yes" if settings.gmail_polling else "no"
    polling_input = input(f"  Enable polling? [{current_polling}]: ").strip().lower()
    polling = polling_input if polling_input in ("yes", "no") else current_polling
    _update_env("ROVEBOT_GMAIL_POLLING", "true" if polling == "yes" else "false")

    if polling == "yes":
        current_interval = str(settings.polling_interval_seconds)
        interval_input = input(f"  Polling interval in seconds [{current_interval}]: ").strip()
        interval = interval_input if interval_input.isdigit() else current_interval
        _update_env("ROVEBOT_POLLING_INTERVAL_SECONDS", interval)
        print()

    # ── Done ─────────────────────────────────────────────────────────────────
    print("=" * 40)
    print("Setup complete. Run:  uv run rovebot")
    print("=" * 40)


def _update_env(key: str, value: str) -> None:
    env_path = Path(".env")
    content = env_path.read_text() if env_path.exists() else ""
    pattern = rf"^{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{replacement}\n"
    env_path.write_text(content)
