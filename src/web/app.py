import html
import re
import threading
from typing import Any

from fastapi import FastAPI, Request

from src.cli.commands import (
    generate_brief_text,
    generate_levels_text,
    generate_tech_text,
    generate_why_text,
)
from src.config.settings import settings
from src.delivery.telegram import send_telegram_message
from src.utils.telegram_formatting import format_brief_for_telegram

app = FastAPI()


def _allowed_chat_ids() -> set[str]:
    raw = settings.ALLOWED_CHAT_IDS.strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _parse_command(text: str) -> tuple[str, list[str]] | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split()
    if not parts:
        return None

    command = parts[0][1:]
    command = command.split("@", 1)[0].lower()
    args = parts[1:]
    return command, args


def _format_why_for_telegram(result: dict[str, str]) -> str:
    return (
        f"<b>{html.escape(result['header'])}</b>\n"
        f"{html.escape(result['trend_line'])}\n\n"
        f"{html.escape(result['explanation'])}"
    )


def _format_levels_for_telegram(result: dict[str, str]) -> str:
    return (
        f"<b>{html.escape(result['header'])}</b>\n\n"
        f"<pre>{html.escape(result['table'])}</pre>"
    )


def _format_tech_for_telegram(result: dict[str, str]) -> str:
    return (
        f"<b>{html.escape(result['header'])}</b>\n\n"
        f"<pre>{html.escape(result['text'])}</pre>"
    )


def _process_command(chat_id: str, command: str, args: list[str]) -> None:
    if command == "brief":
        send_telegram_message("Generating market brief...", chat_id=chat_id)
        brief_date, brief = generate_brief_text()
        formatted = format_brief_for_telegram(brief, brief_date)
        send_telegram_message(formatted, parse_mode="HTML", chat_id=chat_id)
        return

    if command == "why":
        if len(args) != 1:
            send_telegram_message("Usage: /why <symbol>", chat_id=chat_id)
            return
        symbol = re.sub(r"[^A-Za-z0-9.\-]", "", args[0]).upper()
        if not symbol:
            send_telegram_message("Usage: /why <symbol>", chat_id=chat_id)
            return
        send_telegram_message(f"Checking {symbol}...", chat_id=chat_id)
        result = generate_why_text(symbol)
        send_telegram_message(_format_why_for_telegram(result), parse_mode="HTML", chat_id=chat_id)
        return

    if command == "levels":
        if len(args) != 1:
            send_telegram_message("Usage: /levels <symbol>", chat_id=chat_id)
            return
        symbol = re.sub(r"[^A-Za-z0-9.\-]", "", args[0]).upper()
        if not symbol:
            send_telegram_message("Usage: /levels <symbol>", chat_id=chat_id)
            return
        result = generate_levels_text(symbol)
        send_telegram_message(_format_levels_for_telegram(result), parse_mode="HTML", chat_id=chat_id)
        return

    if command == "tech":
        if len(args) != 1:
            send_telegram_message("Usage: /tech <symbol>", chat_id=chat_id)
            return
        symbol = re.sub(r"[^A-Za-z0-9.\-]", "", args[0]).upper()
        if not symbol:
            send_telegram_message("Usage: /tech <symbol>", chat_id=chat_id)
            return
        result = generate_tech_text(symbol)
        send_telegram_message(_format_tech_for_telegram(result), parse_mode="HTML", chat_id=chat_id)
        return


def _handle_update(update: dict[str, Any]) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return

    text = message.get("text")
    if not isinstance(text, str):
        return

    parsed = _parse_command(text)
    if not parsed:
        return
    command, args = parsed
    if command not in {"brief", "why", "levels", "tech"}:
        return

    chat = message.get("chat", {})
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return

    allowed = _allowed_chat_ids()
    if chat_id not in allowed:
        return

    try:
        _process_command(chat_id, command, args)
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
