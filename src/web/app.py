import html
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.alerts.scanner import (
    ERROR_DB_NOT_CONFIGURED,
    ERROR_DB_UNAVAILABLE,
    get_saved_alert_events,
    scan_alert_events,
)
from src.bot.commands import ParsedCommand, parse_command
from src.cli.commands import (
    generate_brief_text,
    generate_levels_text,
    generate_tech_text,
    generate_telegram_why_text,
)
from src.config.settings import settings
from src.delivery.telegram import get_chat_member, pin_telegram_message, send_telegram_message
from src.storage import (
    add_symbol_to_chat_watchlist,
    ensure_chat,
    get_chat_settings,
    get_effective_watchlist,
    is_database_configured,
    load_default_watchlist,
    remove_symbol_from_chat_watchlist,
    set_chat_branding,
    set_chat_brief_time,
    set_chat_pin_daily_brief,
    set_chat_timezone,
)
from src.web.auth import is_request_authorized, is_telegram_webhook_authorized
from src.utils.telegram_formatting import (
    DISCLAIMER_HTML,
    format_brief_for_telegram,
    format_levels_for_telegram,
    format_tech_for_telegram,
    format_why_for_telegram,
)

logger = logging.getLogger(__name__)


def _warn_if_webhook_secret_missing() -> None:
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning(
            "TELEGRAM_WEBHOOK_SECRET is not set: /telegram/webhook accepts unauthenticated "
            "requests. Set it and re-register the webhook with setWebhook secret_token."
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _warn_if_webhook_secret_missing()
    yield


app = FastAPI(lifespan=_lifespan)


def _allowed_chat_ids() -> set[str]:
    raw = settings.ALLOWED_CHAT_IDS.strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_group_chat(chat_type: str) -> bool:
    return chat_type in {"group", "supergroup"}


def _start_text() -> str:
    return (
        "👋 <b>Welcome</b>\n"
        "I send stock + crypto market briefs to this chat.\n\n"
        "<b>Quick commands</b>\n"
        "• /brief\n"
        "• /why BTC\n"
        "• /tech BTC\n"
        "• /levels BTC\n"
        "• /watchlist show\n"
        "• /help\n"
        "• /adminhelp"
    )


def _help_text() -> str:
    return (
        "🙋 <b>Member help</b>\n"
        "Use these commands in this chat:\n"
        "• /brief\n"
        "• /why SYMBOL\n"
        "• /tech SYMBOL\n"
        "• /levels SYMBOL\n"
        "• /alerts\n"
        "• /watchlist show\n"
        "• /settings\n\n"
        "Need setup commands? Use /adminhelp."
    )


def _admin_help_text() -> str:
    return (
        "🛠 <b>Admin setup help</b>\n"
        "Admin-only commands:\n"
        "• /watchlist add BTC NVDA ETH\n"
        "• /watchlist remove DOGE\n"
        "• /watchlist import default\n"
        "• /watchlist reset default\n"
        "• /watchlist clear\n"
        "• /set_branding TEXT\n"
        "• /set_timezone Asia/Singapore\n"
        "• /set_brief_time 09:00\n"
        "• /set_pin_brief on/off\n\n"
        "In groups, only admins can change watchlists/settings."
    )


def _format_alerts_for_telegram(events: list[dict]) -> str:
    if not events:
        return "No saved market alerts found."

    lines: list[str] = []
    sections = [("high", "🔴 <b>HIGH IMPACT</b>"), ("medium", "🟠 <b>MEDIUM IMPACT</b>")]
    for level, title in sections:
        grouped = [e for e in events if str(e.get("impact_level", "")).lower() == level]
        if not grouped:
            continue
        if lines:
            lines.append("")
        lines.append(title)
        for item in grouped:
            score = int(item.get("impact_score") or 0)
            headline = str(item.get("headline") or "").strip() or "(no headline)"
            source = str(item.get("source") or "").strip() or "Unknown"
            symbols = str(item.get("symbols") or "").strip()
            first_seen = str(item.get("first_seen_at") or "").strip()
            category = str(item.get("category") or "").strip()
            url = str(item.get("url") or "").strip()

            if url:
                lines.append(
                    f'• <a href="{html.escape(url, quote=True)}">{html.escape(headline)}</a>'
                )
            else:
                lines.append(f"• {html.escape(headline)}")

            meta_parts = [f"score {score}", source]
            if category:
                meta_parts.append(category)
            if symbols:
                meta_parts.append(f"symbols: {symbols}")
            if first_seen:
                meta_parts.append(f"seen: {first_seen}")
            lines.append(f"  <i>{html.escape(' | '.join(meta_parts))}</i>")

    if not lines:
        return "No saved market alerts found."
    lines.extend(["", DISCLAIMER_HTML])
    return "\n".join(lines)


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


def can_manage_chat(chat_id: str, user_id: str, chat_type: str) -> bool:
    if chat_type == "private":
        # In a real private chat the chat id is the user's own id. Requiring that
        # stops an update claiming type "private" with a group's chat id from
        # inheriting admin rights over that group.
        return bool(user_id) and str(chat_id) == str(user_id)
    if not _is_group_chat(chat_type):
        return False
    try:
        member = get_chat_member(chat_id=chat_id, user_id=user_id)
    except Exception:
        return False
    return str(member.get("status", "")).lower() in {"creator", "administrator"}


def _format_settings_text(chat_id: str, settings_payload: dict, custom_watchlist: bool) -> str:
    branding = settings_payload.get("branding") or "(default)"
    timezone = settings_payload.get("timezone") or "Asia/Singapore"
    brief_time = settings_payload.get("brief_time") or "09:00"
    pin_daily_brief = bool(settings_payload.get("pin_daily_brief"))
    lines = [
        "Settings for this chat:",
        f"- Branding/title: {branding}",
        f"- Timezone: {timezone}",
        f"- Brief time: {brief_time}",
        f"- Pin daily brief: {'on' if pin_daily_brief else 'off'}",
        f"- Custom watchlist: {'yes' if custom_watchlist else 'no'}",
    ]
    return "\n".join(lines)


def _build_watchlist_batch_summary(
    action: str,
    added: list[str],
    existed: list[str],
    removed: list[str],
    missing: list[str],
) -> str:
    lines: list[str] = []
    if action == "add":
        if added:
            lines.append(f"Added: {', '.join(added)}")
        if existed:
            lines.append(f"Already existed: {', '.join(existed)}")
    else:
        if removed:
            lines.append(f"Removed: {', '.join(removed)}")
        if missing:
            lines.append(f"Not found: {', '.join(missing)}")
    if not lines:
        return "No symbols were changed."
    return "\n".join(lines)


def _process_command(
    chat_id: str,
    chat_type: str,
    chat_title: str | None,
    user_id: str,
    parsed: ParsedCommand,
) -> None:
    if parsed.command == "brief":
        send_telegram_message("Generating market brief...", chat_id=chat_id)
        chat_settings = get_chat_settings(chat_id)
        if is_database_configured():
            ensure_chat(chat_id, chat_type=chat_type, title=chat_title)
        watchlist, _ = get_effective_watchlist(chat_id)
        brief_date, brief = generate_brief_text(watchlist=watchlist)
        branding = str(chat_settings.get("branding") or "").strip()
        brief_title = f"{branding} Market Brief" if branding else "MARKET BRIEF"
        formatted = format_brief_for_telegram(brief, brief_date, brief_title=brief_title)
        sent_messages = send_telegram_message(formatted, parse_mode="HTML", chat_id=chat_id)
        if bool(chat_settings.get("pin_daily_brief")) and sent_messages:
            message_id_raw = sent_messages[0].get("message_id")
            try:
                message_id = int(message_id_raw)
                pin_telegram_message(message_id, chat_id=chat_id, disable_notification=True)
            except (TypeError, ValueError):
                pass
            except Exception:
                pass
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

    if parsed.command == "start":
        send_telegram_message(_start_text(), parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "help":
        send_telegram_message(_help_text(), parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "adminhelp":
        send_telegram_message(_admin_help_text(), parse_mode="HTML", chat_id=chat_id)
        return

    if parsed.command == "alerts":
        payload = get_saved_alert_events(hours=24, limit=10)
        if not payload.get("ok"):
            send_telegram_message(
                payload.get("error") or "Could not read saved alerts right now.",
                chat_id=chat_id,
            )
            return
        send_telegram_message(
            _format_alerts_for_telegram(list(payload.get("events", []))),
            parse_mode="HTML",
            chat_id=chat_id,
        )
        return

    if parsed.command == "settings":
        if not is_database_configured():
            send_telegram_message(
                "Custom settings are not enabled yet because DATABASE_URL is not configured.",
                chat_id=chat_id,
            )
            return
        ensure_chat(chat_id, chat_type=chat_type, title=chat_title)
        chat_settings = get_chat_settings(chat_id)
        _, custom_watchlist = get_effective_watchlist(chat_id)
        send_telegram_message(
            _format_settings_text(chat_id, chat_settings, custom_watchlist),
            chat_id=chat_id,
        )
        return

    if parsed.command in {"set_branding", "set_timezone", "set_brief_time", "set_pin_brief"}:
        if not is_database_configured():
            send_telegram_message(
                "Custom settings are not enabled yet because DATABASE_URL is not configured.",
                chat_id=chat_id,
            )
            return
        if not can_manage_chat(chat_id=chat_id, user_id=user_id, chat_type=chat_type):
            send_telegram_message(
                "You are not allowed to modify settings. Only group admins can change settings, and changes are denied if admin status cannot be verified.",
                chat_id=chat_id,
            )
            return

        if parsed.command == "set_branding":
            value = (parsed.value or "").strip()
            status = set_chat_branding(chat_id, value, chat_type=chat_type, title=chat_title)
            if status == "saved":
                send_telegram_message(f"Saved branding/title: {value}", chat_id=chat_id)
                return
            if status == "invalid":
                raise ValueError("Use: /set_branding Crypto Crew")
            raise ValueError("Could not save settings right now.")

        if parsed.command == "set_timezone":
            value = (parsed.value or "").strip()
            status = set_chat_timezone(chat_id, value, chat_type=chat_type, title=chat_title)
            if status == "saved":
                send_telegram_message(f"Saved timezone: {value}", chat_id=chat_id)
                return
            if status == "invalid":
                raise ValueError("Invalid timezone. Example: /set_timezone Asia/Singapore")
            raise ValueError("Could not save settings right now.")

        if parsed.command == "set_brief_time":
            value = (parsed.value or "").strip()
            status = set_chat_brief_time(chat_id, value, chat_type=chat_type, title=chat_title)
            if status == "saved":
                send_telegram_message(
                    "Saved. Per-group scheduled briefs are not enabled yet; this will be used later.",
                    chat_id=chat_id,
                )
                return
            if status == "invalid":
                raise ValueError("Invalid time. Example: /set_brief_time 09:00")
            raise ValueError("Could not save settings right now.")

        value = (parsed.value or "").strip().lower()
        status = set_chat_pin_daily_brief(
            chat_id,
            enabled=(value == "on"),
            chat_type=chat_type,
            title=chat_title,
        )
        if status == "saved":
            send_telegram_message(f"Saved pin daily brief: {value}", chat_id=chat_id)
            return
        raise ValueError("Could not save settings right now.")

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

            if not can_manage_chat(chat_id=chat_id, user_id=user_id, chat_type=chat_type):
                send_telegram_message(
                    "You are not allowed to modify this watchlist. Only group admins can add/remove symbols, and changes are denied if admin status cannot be verified.",
                    chat_id=chat_id,
                )
                return

            symbols = parsed.symbols or ([parsed.symbol] if parsed.symbol else [])
            if not symbols:
                raise ValueError("Use:\n/watchlist show\n/watchlist add BTC\n/watchlist remove NVDA")

            added: list[str] = []
            existed: list[str] = []
            removed: list[str] = []
            missing: list[str] = []

            if parsed.action == "add":
                for symbol in symbols:
                    status = add_symbol_to_chat_watchlist(
                        chat_id=chat_id,
                        symbol=symbol,
                        chat_type=chat_type,
                        title=chat_title,
                    )
                    if status == "added":
                        added.append(symbol)
                    elif status == "exists":
                        existed.append(symbol)
                    else:
                        raise ValueError("Could not update watchlist right now.")
                send_telegram_message(
                    _build_watchlist_batch_summary(
                        action="add",
                        added=added,
                        existed=existed,
                        removed=[],
                        missing=[],
                    ),
                    chat_id=chat_id,
                )
                return

            for symbol in symbols:
                status = remove_symbol_from_chat_watchlist(chat_id=chat_id, symbol=symbol)
                if status == "removed":
                    removed.append(symbol)
                elif status == "missing":
                    missing.append(symbol)
                else:
                    raise ValueError("Could not update watchlist right now.")
            send_telegram_message(
                _build_watchlist_batch_summary(
                    action="remove",
                    added=[],
                    existed=[],
                    removed=removed,
                    missing=missing,
                ),
                chat_id=chat_id,
            )
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
    if not is_request_authorized(request, settings.USAGE_REPORT_TOKEN, "/usage/daily-report"):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    from src.ai.usage import load_records, build_usage_report, _sum_records

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    records = load_records()
    day_recs = [r for r in records if r.get("timestamp", "").startswith(yesterday)]
    _, _, cost = _sum_records(day_recs)

    report = build_usage_report(yesterday)
    send_telegram_message(report, parse_mode="HTML")

    return JSONResponse({"ok": True, "date": yesterday, "estimated_cost_usd": round(cost, 6)})


@app.get("/alerts/scan")
async def alerts_scan(request: Request) -> JSONResponse:
    if not is_request_authorized(request, settings.ALERTS_SCAN_TOKEN, "/alerts/scan"):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    summary = scan_alert_events()
    if summary.get("ok"):
        status_code = 200
    elif summary.get("error") in {ERROR_DB_NOT_CONFIGURED, ERROR_DB_UNAVAILABLE}:
        status_code = 503  # dependency/config problem, not a bug in the scan itself
    else:
        status_code = 500
    return JSONResponse(summary, status_code=status_code)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if not is_telegram_webhook_authorized(request, settings.TELEGRAM_WEBHOOK_SECRET):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    payload = await request.json()
    if not isinstance(payload, dict):
        return {"ok": True}

    worker = threading.Thread(target=_handle_update, args=(payload,), daemon=True)
    worker.start()
    return {"ok": True}
