import requests

from src.config.settings import settings

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MAX_MESSAGE_LEN = 4096
TELEGRAM_SAFE_CHUNK_LEN = 3900


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
) -> None:
    token = _require_telegram_token()
    target_chat_id = str(chat_id) if chat_id is not None else _require_default_chat_id()
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"

    chunks = _split_message(text, TELEGRAM_SAFE_CHUNK_LEN)
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

        response = requests.post(url, json=payload, timeout=20)
        if response.status_code != 200:
            raise RuntimeError(
                f"Telegram API error ({response.status_code}): {response.text}"
            )
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API response not ok: {payload}")
