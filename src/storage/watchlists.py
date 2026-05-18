import pathlib
import re

import yaml

from src.storage.db import get_connection, is_database_configured

ROOT = pathlib.Path(__file__).parent.parent.parent
WATCHLIST_PATH = ROOT / "config" / "watchlist.yaml"
_SYMBOL_SANITIZE_RE = re.compile(r"[^A-Za-z0-9.\-]")

_CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "MATIC", "DOT", "LINK", "LTC", "ATOM",
}
_ETF_SYMBOLS = {"VOO", "QQQ", "DIA", "IWM", "SPY"}


def normalize_symbol(symbol: str) -> str:
    return _SYMBOL_SANITIZE_RE.sub("", symbol).upper()


def infer_asset_type(symbol: str) -> str:
    s = symbol.upper()
    if s in _CRYPTO_SYMBOLS:
        return "crypto"
    if s in _ETF_SYMBOLS:
        return "etf"
    return "stock"


def _normalize_symbol_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        symbol = normalize_symbol(item)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def load_default_watchlist() -> dict[str, list[str]]:
    with open(WATCHLIST_PATH) as f:
        raw = yaml.safe_load(f) or {}
    return {
        "stocks": _normalize_symbol_list(raw.get("stocks", [])),
        "etfs": _normalize_symbol_list(raw.get("etfs", [])),
        "crypto": _normalize_symbol_list(raw.get("crypto", [])),
    }


def ensure_chat(chat_id: str, chat_type: str | None = None, title: str | None = None) -> None:
    if not is_database_configured():
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chats (chat_id, chat_type, title, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (chat_id)
                DO UPDATE SET
                    chat_type = EXCLUDED.chat_type,
                    title = EXCLUDED.title,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (chat_id, chat_type, title),
            )
        conn.commit()
    finally:
        conn.close()


def list_chat_watchlist_items(chat_id: str) -> list[dict]:
    if not is_database_configured():
        return []
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT symbol, asset_type
                FROM watchlist_items
                WHERE chat_id = %s
                ORDER BY created_at ASC, id ASC;
                """,
                (chat_id,),
            )
            rows = cur.fetchall()
        return [{"symbol": str(row[0]), "asset_type": str(row[1])} for row in rows]
    finally:
        conn.close()


def grouped_watchlist_from_items(items: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {"stocks": [], "etfs": [], "crypto": []}
    for item in items:
        symbol = normalize_symbol(str(item.get("symbol", "")))
        if not symbol:
            continue
        asset_type = str(item.get("asset_type", "stock")).lower()
        if asset_type == "crypto":
            grouped["crypto"].append(symbol)
        elif asset_type == "etf":
            grouped["etfs"].append(symbol)
        else:
            grouped["stocks"].append(symbol)
    return grouped


def get_effective_watchlist(chat_id: str) -> tuple[dict[str, list[str]], bool]:
    default = load_default_watchlist()
    if not is_database_configured():
        return default, False
    try:
        items = list_chat_watchlist_items(chat_id)
    except Exception:
        return default, False
    if not items:
        return default, False
    return grouped_watchlist_from_items(items), True


def add_symbol_to_chat_watchlist(
    chat_id: str,
    symbol: str,
    chat_type: str | None = None,
    title: str | None = None,
) -> str:
    if not is_database_configured():
        return "not_enabled"

    norm_symbol = normalize_symbol(symbol)
    if not norm_symbol:
        return "invalid_symbol"

    ensure_chat(chat_id, chat_type=chat_type, title=title)
    asset_type = infer_asset_type(norm_symbol)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO watchlist_items (chat_id, symbol, asset_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_id, symbol) DO NOTHING
                RETURNING id;
                """,
                (chat_id, norm_symbol, asset_type),
            )
            inserted = cur.fetchone() is not None
            cur.execute(
                "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = %s;",
                (chat_id,),
            )
        conn.commit()
    finally:
        conn.close()

    return "added" if inserted else "exists"


def remove_symbol_from_chat_watchlist(chat_id: str, symbol: str) -> str:
    if not is_database_configured():
        return "not_enabled"

    norm_symbol = normalize_symbol(symbol)
    if not norm_symbol:
        return "invalid_symbol"

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM watchlist_items
                WHERE chat_id = %s AND symbol = %s
                RETURNING id;
                """,
                (chat_id, norm_symbol),
            )
            removed = cur.fetchone() is not None
            cur.execute(
                "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = %s;",
                (chat_id,),
            )
        conn.commit()
    finally:
        conn.close()

    return "removed" if removed else "missing"
