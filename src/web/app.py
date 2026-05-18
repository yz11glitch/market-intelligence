import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.bot.commands import ParsedCommand, parse_command
from src.cli.commands import (
    generate_brief_text,
    generate_levels_text,
    generate_tech_text,
    generate_telegram_why_text,
)
from src.config.settings import settings
from src.delivery.telegram import get_chat_member, send_telegram_message
from src.storage import (
    add_symbol_to_chat_watchlist,
    ensure_chat,
    get_effective_watchlist,
    is_database_configured,
    load_default_watchlist,
    remove_symbol_from_chat_watchlist,
)
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
        "/watchlist show\n"
        "/watchlist add BTC\n"
        "/watchlist remove NVDA\n"
        "/help"
    )


def _format_watchlist_text(chat_id: str) -> str:
    if not is_database_configured():
        watchlist = load_default_watchlist()
        header = "Using default watchlist from config/watchlist.yaml (DATABASE_URL is not configured)."
    else:
        watchlist, is_custom = get_effective_watchlist(chat_id)
        header = (
            "Using custom watchlist for this chat."
            if is_custom
            else "Using default watchlist from config/watchlist.yaml."
        )

    lines = [header, "", "Symbols:"]
    stocks = watchlist.get("stocks", [])
    etfs = watchlist.get("etfs", [])
    crypto = watchlist.get("crypto", [])
    if stocks:
        lines.append(f"Stocks: {', '.join(stocks)}")
    if etfs:
        lines.append(f"ETFs: {', '.join(etfs)}")
    if crypto:
        lines.append(f"Crypto: {', '.join(crypto)}")
    if not (stocks or etfs or crypto):
        lines.append("(none)")
    return "\n".join(lines)


def can_manage_watchlist(chat_id: str, user_id: str, chat_type: str) -> bool:
    if chat_type == "private":
        return True
    if not _is_group_chat(chat_type):
        return False
    try:
        member = get_chat_member(chat_id=chat_id, user_id=user_id)
    except Exception:
        return False
    return str(member.get("status", "")).lower() in {"creator", "administrator"}


def _process_command(
    chat_id: str,
    chat_type: str,
    chat_title: str | None,
    user_id: str,
    parsed: ParsedCommand,
) -> None:
    if parsed.command == "brief":
        send_telegram_message("Generating market brief...", chat_id=chat_id)
        if is_database_configured():
            ensure_chat(chat_id, chat_type=chat_type, title=chat_title)
        watchlist, _ = get_effective_watchlist(chat_id)
        brief_date, brief = generate_brief_text(watchlist=watchlist)
        formatted = format_brief_for_telegram(brief, brief_date)
        send_telegram_message(formatted, parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "why":
        if not parsed.symbol:
            raise ValueError("Use: /why BTC")
        symbol = parsed.symbol
        send_telegram_message(f"Checking {symbol}...", chat_id=chat_id)
        result = generate_telegram_why_text(symbol)
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

    if parsed.command == "watchlist":
        if parsed.action == "show":
            send_telegram_message(_format_watchlist_text(chat_id), chat_id=chat_id)
            return

        if parsed.action in {"add", "remove"}:
            if not is_database_configured():
                send_telegram_message(
                    "Custom watchlists are not enabled yet because DATABASE_URL is not configured.",
                    chat_id=chat_id,
                )
                return

            if not can_manage_watchlist(chat_id=chat_id, user_id=user_id, chat_type=chat_type):
                send_telegram_message(
                    "You are not allowed to modify this watchlist. Only group admins can add/remove symbols, and changes are denied if admin status cannot be verified.",
                    chat_id=chat_id,
                )
                return

            symbol = parsed.symbol or ""
            if parsed.action == "add":
                status = add_symbol_to_chat_watchlist(
                    chat_id=chat_id,
                    symbol=symbol,
                    chat_type=chat_type,
                    title=chat_title,
                )
                if status == "added":
                    send_telegram_message(f"Added {symbol.upper()} to this chat watchlist.", chat_id=chat_id)
                    return
                if status == "exists":
                    send_telegram_message(f"{symbol.upper()} is already in this chat watchlist.", chat_id=chat_id)
                    return
                raise ValueError("Could not update watchlist right now.")

            status = remove_symbol_from_chat_watchlist(chat_id=chat_id, symbol=symbol)
            if status == "removed":
                send_telegram_message(f"Removed {symbol.upper()} from this chat watchlist.", chat_id=chat_id)
                return
            if status == "missing":
                send_telegram_message(f"{symbol.upper()} is not in this chat watchlist.", chat_id=chat_id)
                return
            raise ValueError("Could not update watchlist right now.")


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
    chat_title_raw = chat.get("title") or chat.get("username") or ""
    chat_title = str(chat_title_raw).strip() or None
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", "")).strip()
    if not user_id:
        return
    if _is_group_chat(chat_type) and not text.lstrip().startswith("/"):
        return

    parsed = parse_command(text)
    if not parsed:
        return

    if parsed.usage_error:
        send_telegram_message(parsed.usage_error, chat_id=chat_id)
        return

    try:
        _process_command(chat_id, chat_type, chat_title, user_id, parsed)
    except ValueError as e:
        send_telegram_message(str(e), chat_id=chat_id)
    except Exception:
        send_telegram_message("Sorry, command failed. Please try again.", chat_id=chat_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/usage/daily-report")
async def usage_daily_report(request: Request) -> JSONResponse:
    token = request.query_params.get("token", "")
    expected = settings.USAGE_REPORT_TOKEN
    if not expected or token != expected:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    from src.ai.usage import load_records, build_usage_report, _sum_records

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    records = load_records()
    day_recs = [r for r in records if r.get("timestamp", "").startswith(yesterday)]
    _, _, cost = _sum_records(day_recs)

    report = build_usage_report(yesterday)
    send_telegram_message(report, parse_mode="HTML")

    return JSONResponse({"ok": True, "date": yesterday, "estimated_cost_usd": round(cost, 6)})


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    payload = await request.json()
    if not isinstance(payload, dict):
        return {"ok": True}

    worker = threading.Thread(target=_handle_update, args=(payload,), daemon=True)
    worker.start()
    return {"ok": True}
