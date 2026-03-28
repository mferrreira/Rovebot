# Customer Response Agent - Rovebot

Rovebot v0 is a deterministic email-processing backend for Gmail intake, context assembly, LLM drafting, and Slack-based human approval.

## Local development

1. Install dependencies: `uv sync --extra dev`
2. Run the setup wizard: `uv run rovebot setup`
3. Run the app: `uv run rovebot`
4. Run tests: `uv run pytest`

## CLI

- `uv run rovebot setup`: interactive wizard that fills or updates `.env`

## Environment variables

Create `.env` from `.env.example` and fill the real credentials before starting the app.

### Base app config

`ROVEBOT_ENV`
- Use `development`, `test`, or `production`.

`ROVEBOT_KNOWLEDGE_DIR`
- Directory with local Markdown documents used as internal context.
- Default is `knowledge`.

### LLM

`ROVEBOT_CLASSIFY_MODEL`
- Anthropic model used for email classification.

`ROVEBOT_DRAFT_MODEL`
- Anthropic model used for draft generation and learning extraction.

`ROVEBOT_ANTHROPIC_API_KEY`
- Get it from the Anthropic Console:
- Go to `console.anthropic.com`
- Open API keys
- Create a key and copy it into `.env`

`ROVEBOT_ANTHROPIC_BASE_URL`
- Keep the default unless you intentionally route through a proxy.

### Gmail

`ROVEBOT_GMAIL_API_BASE_URL`
- Keep the Google default unless you are routing through an internal gateway.

`ROVEBOT_GMAIL_ACCESS_TOKEN`
- Current Gmail API bearer token. The setup wizard can populate it for you.

`ROVEBOT_GMAIL_REFRESH_TOKEN`
- Refresh token used to renew Gmail access automatically.

`ROVEBOT_GMAIL_CLIENT_ID`
- Google OAuth client ID used by the local Gmail setup flow.

`ROVEBOT_GMAIL_CLIENT_SECRET`
- Google OAuth client secret used by the local Gmail setup flow.

`ROVEBOT_GMAIL_POLLING`
- Enable or disable the local background polling loop.

`ROVEBOT_POLLING_INTERVAL_SECONDS`
- Polling interval when `ROVEBOT_GMAIL_POLLING=true`.

Important:
- The local setup flow uses OAuth on `http://localhost:8080/callback`, so this URI must be allowed in your Google OAuth app.
- The bot only processes inbox arrivals in polling mode.

### Slack

`ROVEBOT_SLACK_BOT_TOKEN`
- Get it from your Slack app:
- Go to `api.slack.com/apps`
- Create or open the app
- Enable the required bot scopes for posting messages and interactive actions
- Install the app to the workspace
- Copy the Bot User OAuth Token (`xoxb-...`)

`ROVEBOT_SLACK_SIGNING_SECRET`
- Signing secret used to validate Slack interactivity requests.

`ROVEBOT_SLACK_API_URL`
- Keep the default unless you need a proxy.

`ROVEBOT_SLACK_CHANNEL`
- Channel where draft approvals will be posted, for example `#ops-email-review`.

Important:
- If you run locally, Slack interactivity needs a public URL that tunnels to your machine, such as `ngrok` or `cloudflared`.
- Point your Slack Interactivity Request URL to `https://<public-url>/webhooks/slack/actions`.

## Suggested setup flow

1. Copy `.env.example` to `.env`.
2. Create the Slack app and fill `ROVEBOT_SLACK_BOT_TOKEN` and `ROVEBOT_SLACK_SIGNING_SECRET`.
3. Create the Anthropic API key and fill `ROVEBOT_ANTHROPIC_API_KEY`.
4. Run `uv run rovebot setup` to complete Gmail OAuth and local config.
5. If you want Slack buttons working locally, expose the app with a tunnel and configure the Slack Interactivity Request URL.
6. Run `uv run rovebot` and send a test email into the connected Gmail inbox.
