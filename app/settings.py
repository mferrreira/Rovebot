from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ROVEBOT_", extra="ignore")

    env: str = Field(default="development")
    llm_model: str = Field(default="claude-sonnet-4-20250514")
    knowledge_dir: Path = Field(default=Path("knowledge"))
    history_id_file: Path = Field(default=Path("last_history_id.txt"))
    gmail_webhook_token: str = Field(default="dev-gmail-token")
    pubsub_audience: str = Field(default="")
    pubsub_skip_auth: bool = Field(default=False)
    gmail_api_base_url: str = Field(default="https://gmail.googleapis.com/gmail/v1")
    gmail_access_token: str | None = None
    gmail_client_id: str | None
    gmail_client_secret: str
    anthropic_api_key: str | None = None
    anthropic_base_url: str = Field(default="https://api.anthropic.com/v1/messages")
    slack_bot_token: str | None = None
    slack_api_url: str = Field(default="https://slack.com/api/chat.postMessage")
    slack_channel: str = Field(default="#ops-email-review")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
