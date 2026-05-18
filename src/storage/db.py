import threading

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - dependency is declared in requirements
    psycopg = None  # type: ignore[assignment]

from src.config.settings import settings

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def is_database_configured() -> bool:
    return bool(settings.DATABASE_URL.strip())


def _create_tables_if_needed() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        if psycopg is None:
            raise RuntimeError("psycopg is required for database-backed watchlists.")
        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chats (
                        chat_id TEXT PRIMARY KEY,
                        chat_type TEXT,
                        title TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS watchlist_items (
                        id SERIAL PRIMARY KEY,
                        chat_id TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                        symbol TEXT NOT NULL,
                        asset_type TEXT NOT NULL DEFAULT 'unknown',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chat_id, symbol)
                    );
                    """
                )
            conn.commit()
            _SCHEMA_READY = True
        finally:
            conn.close()


def get_connection() -> "psycopg.Connection":
    if not is_database_configured():
        raise ValueError("DATABASE_URL is not configured.")
    if psycopg is None:
        raise RuntimeError("psycopg is required for database-backed watchlists.")
    _create_tables_if_needed()
    return psycopg.connect(settings.DATABASE_URL)
