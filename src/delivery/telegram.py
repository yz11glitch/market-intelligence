import json
from pathlib import Path

import requests

from src.config.settings import settings

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MAX_MESSAGE_LEN = 4096
TELEGRAM_SAFE_CHUNK_LEN = 3900
PIN_STATE_PATH = Path(".cache/telegram_daily_brief_pins.json")


def _require_telegram_token() -> str:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable.")
    return token


def _require_default_chat_id() -> str:
    chat_id = settings.TELEGRAM_CHAT_ID.strip()
    if not chat_id:
        raise ValueError("Missing TELEGRAM_CHAT_ID environment variable.")
    return chat_id


def _post_telegram_method(token: str, method: str, payload: dict) -> dict:
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    response = requests.post(url, json=payload, timeout=20)
    if response.status_code != 200:
        raise RuntimeError(f"Telegram API error ({response.status_code}): {response.text}")
    api_payload = response.json()
    if not api_payload.get("ok"):
        raise RuntimeError(f"Telegram API response not ok: {api_payload}")
    return api_payload


def get_chat_member(chat_id: str | int, user_id: str | int) -> dict:
    token = _require_telegram_token()
    payload = {"chat_id": str(chat_id), "user_id": int(user_id)}
    api_payload = _post_telegram_method(token, "getChatMember", payload)
    result = api_payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Telegram getChatMember returned an invalid response.")
    return result


def _split_message(text: str, max_len: int = TELEGRAM_SAFE_CHUNK_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            chunks.append(rest)
            break

        split_at = rest.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunk = rest[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        rest = rest[split_at:].lstrip("\n")

    return chunks


def send_telegram_message(
    text: str,
    parse_mode: str | None = None,
    chat_id: str | int | None = None,
) -> list[dict]:
    token = _require_telegram_token()
    target_chat_id = str(chat_id) if chat_id is not None else _require_default_chat_id()

    chunks = _split_message(text, TELEGRAM_SAFE_CHUNK_LEN)
    sent_messages: list[dict] = []
    for chunk in chunks:
        if len(chunk) > TELEGRAM_MAX_MESSAGE_LEN:
            raise ValueError("Telegram message chunk exceeds Telegram max length.")

        payload = {
            "chat_id": target_chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        api_payload = _post_telegram_method(token, "sendMessage", payload)
        result = api_payload.get("result")
        if isinstance(result, dict):
            sent_messages.append(result)
    return sent_messages


def pin_telegram_message(
    message_id: int,
    chat_id: str | int | None = None,
    disable_notification: bool = True,
) -> None:
    token = _require_telegram_token()
    target_chat_id = str(chat_id) if chat_id is not None else _require_default_chat_id()
    payload = {
        "chat_id": target_chat_id,
        "message_id": message_id,
        "disable_notification": disable_notification,
    }
    _post_telegram_method(token, "pinChatMessage", payload)


def unpin_telegram_message(message_id: int, chat_id: str | int | None = None) -> None:
    token = _require_telegram_token()
    target_chat_id = str(chat_id) if chat_id is not None else _require_default_chat_id()
    payload = {"chat_id": target_chat_id, "message_id": message_id}
    _post_telegram_method(token, "unpinChatMessage", payload)


def _load_pin_state() -> dict[str, int]:
    if not PIN_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(PIN_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    state: dict[str, int] = {}
    for key, value in payload.items():
        try:
            state[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return state


def _save_pin_state(state: dict[str, int]) -> None:
    PIN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIN_STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def maybe_pin_daily_brief(sent_messages: list[dict], chat_id: str | int | None = None) -> None:
    if not settings.TELEGRAM_PIN_DAILY_BRIEF:
        return
    if not sent_messages:
        print("  [telegram] No sent message available to pin.")
        return

    primary = sent_messages[0]
    message_id_raw = primary.get("message_id")
    try:
        message_id = int(message_id_raw)
    except (TypeError, ValueError):
        print("  [telegram] Could not determine message_id for pinning.")
        return

    resolved_chat_id = str(chat_id) if chat_id is not None else _require_default_chat_id()

    try:
        state = _load_pin_state()
        previous_message_id = state.get(resolved_chat_id)

        if (
            settings.TELEGRAM_UNPIN_PREVIOUS_DAILY_BRIEF
            and previous_message_id is not None
            and previous_message_id != message_id
        ):
            try:
                unpin_telegram_message(previous_message_id, chat_id=resolved_chat_id)
            except Exception as e:
                print(f"  [telegram] Unpin previous brief failed: {e}")

        pin_telegram_message(message_id, chat_id=resolved_chat_id, disable_notification=True)
        state[resolved_chat_id] = message_id
        _save_pin_state(state)
        print(f"  [telegram] Pinned daily brief message {message_id}.")
    except Exception as e:
        print(f"  [telegram] Pin daily brief failed: {e}")
