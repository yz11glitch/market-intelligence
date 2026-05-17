import threading
from typing import Any

from fastapi import FastAPI, Request

from src.bot.commands import ParsedCommand, parse_command
from src.cli.commands import (
    generate_brief_text,
    generate_levels_text,
    generate_tech_text,
    generate_why_text,
)
from src.config.settings import settings
from src.delivery.telegram import send_telegram_message
from src.utils.telegram_formatting import (
    format_brief_for_telegram,
    format_levels_for_telegram,
    format_tech_for_telegram,
    format_why_for_telegram,
)

app = FastAPI()


def _allowed_chat_ids() -> set[str]:
    raw = settings.ALLOWED_CHAT_IDS.strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_group_chat(chat_type: str) -> bool:
    return chat_type in {"group", "supergroup"}


def _help_text() -> str:
    return (
        "Commands:\n"
        "/brief\n"
        "/why SYMBOL\n"
        "/levels SYMBOL\n"
        "/tech SYMBOL\n"
        "/help"
    )


def _process_command(chat_id: str, parsed: ParsedCommand) -> None:
    if parsed.command == "brief":
        send_telegram_message("Generating market brief...", chat_id=chat_id)
        brief_date, brief = generate_brief_text()
        formatted = format_brief_for_telegram(brief, brief_date)
        send_telegram_message(formatted, parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "why":
        if not parsed.symbol:
            raise ValueError("Use: /why BTC")
        symbol = parsed.symbol
        send_telegram_message(f"Checking {symbol}...", chat_id=chat_id)
        result = generate_why_text(symbol)
        send_telegram_message(format_why_for_telegram(result), parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "levels":
        if not parsed.symbol:
            raise ValueError("Use: /levels NVDA")
        symbol = parsed.symbol
        result = generate_levels_text(symbol)
        send_telegram_message(format_levels_for_telegram(result), parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "tech":
        if not parsed.symbol:
            raise ValueError("Use: /tech XRP")
        symbol = parsed.symbol
        result = generate_tech_text(symbol)
        send_telegram_message(format_tech_for_telegram(result), parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "help":
        send_telegram_message(_help_text(), chat_id=chat_id)
        return


def _handle_update(update: dict[str, Any]) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return

    chat = message.get("chat", {})
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return

    allowed = _allowed_chat_ids()
    if chat_id not in allowed:
        return

    text = message.get("text")
    if not isinstance(text, str):
        return

    chat_type = str(chat.get("type", "")).lower()
    if _is_group_chat(chat_type) and not text.lstrip().startswith("/"):
        return

    parsed = parse_command(text)
    if not parsed:
        return

    if parsed.usage_error:
        send_telegram_message(parsed.usage_error, chat_id=chat_id)
        return

    try:
        _process_command(chat_id, parsed)
    except ValueError as e:
        send_telegram_message(str(e), chat_id=chat_id)
    except Exception:
        send_telegram_message("Sorry, command failed. Please try again.", chat_id=chat_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    payload = await request.json()
    if not isinstance(payload, dict):
        return {"ok": True}

    worker = threading.Thread(target=_handle_update, args=(payload,), daemon=True)
    worker.start()
    return {"ok": True}
