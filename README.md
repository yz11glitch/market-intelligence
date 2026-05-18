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

Optional daily brief pinning:
- `TELEGRAM_PIN_DAILY_BRIEF=true` to pin the sent daily brief message.
- `TELEGRAM_UNPIN_PREVIOUS_DAILY_BRIEF=true` to unpin the previously tracked pinned daily brief before pinning the new one.
- Defaults are `false`.

### Telegram setup

1. Create a bot with **BotFather** and copy the bot token.
2. Add the bot to your target Telegram group.
3. Get the group chat ID and set `TELEGRAM_CHAT_ID`.
4. To pin daily briefs, make the bot a group admin and grant **Pin messages** permission.

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
- `/start`
- `/brief`
- `/why BTC`
- `/levels ETH`
- `/tech BTC`
- `/adminhelp`
- `/settings`
- `/set_branding Crypto Crew`
- `/set_timezone Asia/Singapore`
- `/set_brief_time 09:00`
- `/set_pin_brief on`
- `/watchlist show`
- `/watchlist add BTC ETH SOL`
- `/watchlist remove NVDA TSLA`
- `/help`

Non-command group messages are ignored.

### Environment

Set:
- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_CHAT_IDS=-1001234567890,123456789`
- `DATABASE_URL=postgresql://...` (optional; enables per-chat custom watchlists)

`ALLOWED_CHAT_IDS` is a comma-separated allowlist. Chats not in this list are ignored silently.
If `DATABASE_URL` is not set, `/brief` and `/watchlist show` use `config/watchlist.yaml`, `/watchlist add/remove` is disabled, and `/settings` / `/set_*` commands are disabled.

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

- `/start` = quick onboarding + key commands for this chat
- `/brief` = market story update (news, macro, catalysts, events)
- `/why TICKER` = mixed narrative with sources
- `/levels TICKER` = raw levels/moving-average numbers
- `/tech TICKER` = interpreted technical read from existing technical data
- `/settings` = show chat settings (branding/title, timezone, brief time, pin setting, custom watchlist)
- `/set_branding TEXT` = set brief title branding for this chat (group admins only in groups)
- `/set_timezone TIMEZONE` = set timezone (group admins only in groups)
- `/set_brief_time HH:MM` = store preferred brief time for future scheduled briefs (group admins only in groups)
- `/set_pin_brief on|off` = control pin behavior for Telegram `/brief` in this chat (group admins only in groups)
- `/watchlist show` = show current chat watchlist source + symbols
- `/watchlist add TICKER [TICKER...]` = add one or more symbols to current chat watchlist (group admins only in groups)
- `/watchlist remove TICKER [TICKER...]` = remove one or more symbols from current chat watchlist (group admins only in groups)
- `/help` = member-focused command reference
- `/adminhelp` = admin-only setup/config command reference
