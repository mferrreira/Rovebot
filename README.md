# Rovebot

Rovebot v0 is a deterministic email-processing backend for Gmail intake, context assembly, LLM drafting, and Slack-based human approval.

## Local development

1. Install dependencies: `uv sync --extra dev`
2. Run the API: `uv run uvicorn app.main:app --reload`
3. Run tests: `uv run pytest`

## Environment variables

Create `.env` from `.env.example` and fill the real credentials before starting the app.

### Base app config

`ROVEBOT_ENV`
- Use `development`, `test`, or `production`.

`ROVEBOT_KNOWLEDGE_DIR`
- Directory with local Markdown documents used as internal context.
- Default is `knowledge`.

### LLM

`ROVEBOT_LLM_MODEL`
- Pick the Anthropic model you want to use for drafting.

`ROVEBOT_ANTHROPIC_API_KEY`
- Get it from the Anthropic Console:
- Go to `console.anthropic.com`
- Open API keys
- Create a key and copy it into `.env`

`ROVEBOT_ANTHROPIC_BASE_URL`
- Keep the default unless you intentionally route through a proxy.

### Gmail

`ROVEBOT_GMAIL_WEBHOOK_TOKEN`
- Shared secret used by this app to accept webhook calls.
- Generate a random token locally, for example with `openssl rand -hex 32`, and configure the caller to send it in `X-Rovebot-Token`.

`ROVEBOT_PUBSUB_AUDIENCE`
- Audience expected in the OIDC token sent by the Pub/Sub push subscription.
- In practice this should be the full URL of your Pub/Sub endpoint, for example `https://rovebot.example.com/webhooks/gmail/pubsub`.

`ROVEBOT_GMAIL_API_BASE_URL`
- Keep the Google default unless you are routing through an internal gateway.

`ROVEBOT_GMAIL_ACCESS_TOKEN`
- The current code expects a valid Gmail API bearer token.
- Generate it through your Google OAuth flow and inject the access token into `.env`.

Important:
- The Gmail adapter is scaffolded, but OAuth/access-token management is not complete yet.
- Before production use, you still need to finish Gmail authentication and webhook delivery setup in Google Cloud.

### Slack

`ROVEBOT_SLACK_BOT_TOKEN`
- Get it from your Slack app:
- Go to `api.slack.com/apps`
- Create or open the app
- Enable the required bot scopes for posting messages and interactive actions
- Install the app to the workspace
- Copy the Bot User OAuth Token (`xoxb-...`)

`ROVEBOT_SLACK_API_URL`
- Keep the default unless you need a proxy.

`ROVEBOT_SLACK_CHANNEL`
- Channel where draft approvals will be posted, for example `#ops-email-review`.

## Suggested setup flow

1. Copy `.env.example` to `.env`.
2. Create the Slack app and fill `ROVEBOT_SLACK_BOT_TOKEN`.
3. Create the Anthropic API key and fill `ROVEBOT_ANTHROPIC_API_KEY`.
4. Finish Gmail OAuth/webhook setup and fill `ROVEBOT_GMAIL_ACCESS_TOKEN`.
5. Start the API and validate the webhook end to end.
