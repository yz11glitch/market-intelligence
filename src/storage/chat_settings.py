import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.storage.db import get_connection, is_database_configured
from src.storage.watchlists import ensure_chat

DEFAULT_TIMEZONE = "Asia/Singapore"
DEFAULT_BRIEF_TIME = "09:00"
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def default_chat_settings() -> dict:
    return {
        "branding": None,
        "timezone": DEFAULT_TIMEZONE,
        "brief_time": DEFAULT_BRIEF_TIME,
        "pin_daily_brief": False,
    }


def validate_timezone(value: str) -> bool:
    tz = value.strip()
    if not tz or len(tz) > 64 or "/" not in tz:
        return False
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        return False
    return True


def validate_brief_time(value: str) -> bool:
    return bool(_TIME_RE.match(value.strip()))


def get_chat_settings(chat_id: str) -> dict:
    defaults = default_chat_settings()
    if not is_database_configured():
        return defaults

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT branding, timezone, brief_time, pin_daily_brief
                    FROM chat_settings
                    WHERE chat_id = %s;
                    """,
                    (chat_id,),
                )
                row = cur.fetchone()
            if not row:
                return defaults
            return {
                "branding": str(row[0]).strip() if row[0] is not None and str(row[0]).strip() else None,
                "timezone": str(row[1] or DEFAULT_TIMEZONE),
                "brief_time": str(row[2] or DEFAULT_BRIEF_TIME),
                "pin_daily_brief": bool(row[3]),
            }
        finally:
            conn.close()
    except Exception:
        return defaults


def _upsert_chat_settings(
    chat_id: str,
    *,
    branding: str | None = None,
    timezone: str | None = None,
    brief_time: str | None = None,
    pin_daily_brief: bool | None = None,
    chat_type: str | None = None,
    title: str | None = None,
) -> str:
    if not is_database_configured():
        return "not_enabled"

    try:
        ensure_chat(chat_id, chat_type=chat_type, title=title)
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_settings (
                        chat_id, branding, timezone, brief_time, pin_daily_brief, updated_at
                    )
                    VALUES (
                        %s, %s, COALESCE(%s, %s), COALESCE(%s, %s), COALESCE(%s, %s), CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (chat_id)
                    DO UPDATE SET
                        branding = COALESCE(EXCLUDED.branding, chat_settings.branding),
                        timezone = COALESCE(EXCLUDED.timezone, chat_settings.timezone),
                        brief_time = COALESCE(EXCLUDED.brief_time, chat_settings.brief_time),
                        pin_daily_brief = COALESCE(EXCLUDED.pin_daily_brief, chat_settings.pin_daily_brief),
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        chat_id,
                        branding,
                        timezone,
                        DEFAULT_TIMEZONE,
                        brief_time,
                        DEFAULT_BRIEF_TIME,
                        pin_daily_brief,
                        False,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return "unavailable"

    return "saved"


def set_chat_branding(
    chat_id: str,
    branding: str,
    *,
    chat_type: str | None = None,
    title: str | None = None,
) -> str:
    cleaned = branding.strip()
    if not cleaned:
        return "invalid"
    return _upsert_chat_settings(chat_id, branding=cleaned, chat_type=chat_type, title=title)


def set_chat_timezone(
    chat_id: str,
    timezone: str,
    *,
    chat_type: str | None = None,
    title: str | None = None,
) -> str:
    cleaned = timezone.strip()
    if not validate_timezone(cleaned):
        return "invalid"
    return _upsert_chat_settings(chat_id, timezone=cleaned, chat_type=chat_type, title=title)


def set_chat_brief_time(
    chat_id: str,
    brief_time: str,
    *,
    chat_type: str | None = None,
    title: str | None = None,
) -> str:
    cleaned = brief_time.strip()
    if not validate_brief_time(cleaned):
        return "invalid"
    return _upsert_chat_settings(chat_id, brief_time=cleaned, chat_type=chat_type, title=title)


def set_chat_pin_daily_brief(
    chat_id: str,
    enabled: bool,
    *,
    chat_type: str | None = None,
    title: str | None = None,
) -> str:
    return _upsert_chat_settings(
        chat_id,
        pin_daily_brief=enabled,
        chat_type=chat_type,
        title=title,
    )
