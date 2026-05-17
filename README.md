# Market Intelligence CLI

## Telegram daily brief (Stage 1)

This project can send the existing `brief` output to a Telegram group on a GitHub Actions cron job.

### Local usage

1. Generate brief only:
   `python main.py brief`
2. Generate + send to Telegram:
   `python main.py brief --send-telegram`

`--send-telegram` requires:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Telegram setup

1. Create a bot with **BotFather** and copy the bot token.
2. Add the bot to your target Telegram group.
3. Get the group chat ID and set `TELEGRAM_CHAT_ID`.

### GitHub Actions setup

Add these repository secrets:
- `OPENAI_API_KEY`
- `FINNHUB_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Workflow file:
- `.github/workflows/daily-brief.yml`

Run it manually from **Actions → Daily Brief → Run workflow** to test.

## Telegram group commands (Stage 2)

Webhook backend supports slash commands in allowed chats:
- `/brief`
- `/why BTC`
- `/levels ETH`
- `/tech BTC`

Non-command group messages are ignored.

### Environment

Set:
- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_CHAT_IDS=-1001234567890,123456789`

`ALLOWED_CHAT_IDS` is a comma-separated allowlist. Chats not in this list are ignored silently.

### Run on Render

Start command:
`uvicorn src.web.app:app --host 0.0.0.0 --port $PORT`

Health endpoint:
- `GET /health`

Telegram webhook endpoint:
- `POST /telegram/webhook`

Set Telegram webhook:
`https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=<RENDER_URL>/telegram/webhook`

### Local webhook testing

You can run the app locally with uvicorn and send sample updates to `/telegram/webhook` using curl or Postman.

## Command roles

- `/brief` = market story update (news, macro, catalysts, events)
- `/why TICKER` = mixed narrative with sources
- `/levels TICKER` = raw levels/moving-average numbers
- `/tech TICKER` = interpreted technical read from existing technical data
