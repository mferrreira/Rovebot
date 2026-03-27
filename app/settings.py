from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ROVEBOT_", extra="ignore")

    env: str = Field(default="development")
    classify_model: str = Field(default="claude-haiku-4-5-20251001")
    draft_model: str = Field(default="claude-haiku-4-5-20251001")
    knowledge_dir: Path = Field(default=Path("knowledge"))
    learning_file: Path = Field(default=Path("knowledge/learning.md"))
    history_id_file: Path = Field(default=Path("last_history_id.txt"))
    gmail_polling: bool = Field(default=False)
    polling_interval_seconds: int = Field(default=10)
    gmail_webhook_token: str = Field(default="dev-gmail-token")
    cron_token: str = Field(default="dev-cron-token")
    pubsub_audience: str = Field(default="")
    pubsub_skip_auth: bool = Field(default=False)
    gmail_api_base_url: str = Field(default="https://gmail.googleapis.com/gmail/v1")
    gmail_timeout: float = Field(default=30.0)
    gmail_access_token: str | None = None
    gmail_refresh_token: str | None = None
    gmail_client_id: str | None
    gmail_client_secret: str
    anthropic_api_key: str | None = None
    anthropic_base_url: str = Field(default="https://api.anthropic.com/v1/messages")
    slack_bot_token: str | None = None
    slack_api_url: str = Field(default="https://slack.com/api/chat.postMessage")
    slack_channel: str = Field(default="#ops-email-review")
    sender_name: str = Field(default="")
    slack_signing_secret: str | None = None
    slack_views_url: str = Field(default="https://slack.com/api/views.open")
    slack_update_url: str = Field(default="https://slack.com/api/chat.update")
    draft_store_file: Path = Field(default=Path("drafts_store.json"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
