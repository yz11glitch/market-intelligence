import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from src.alerts.scorer import score_news_event
from src.config.settings import settings
from src.data.news import get_general_crypto_news, get_general_market_news
from src.storage.db import get_connection, is_database_configured
from src.storage.watchlists import load_default_watchlist

logger = logging.getLogger(__name__)

# Stable error codes returned by scan_alert_events(). The "detail" text is safe to
# show in public CI logs: it never includes the raw exception message, which for
# connection errors can contain the database host/user.
ERROR_DB_NOT_CONFIGURED = "database_not_configured"
ERROR_DB_UNAVAILABLE = "database_unavailable"
ERROR_SCAN_FAILED = "scan_failed"


def _headline_fingerprint(headline: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _watchlist_terms() -> list[str]:
    watchlist = load_default_watchlist()
    terms: list[str] = []
    for key in ("stocks", "etfs", "crypto"):
        for symbol in watchlist.get(key, []):
            if isinstance(symbol, str) and symbol.strip():
                terms.append(symbol.strip())
    return terms


def _event_exists(conn, url: str | None, fingerprint: str) -> bool:
    with conn.cursor() as cur:
        if url:
            cur.execute(
                """
                SELECT 1
                FROM news_events
                WHERE url = %s OR headline_fingerprint = %s
                LIMIT 1;
                """,
                (url, fingerprint),
            )
        else:
            cur.execute(
                """
                SELECT 1
                FROM news_events
                WHERE headline_fingerprint = %s
                LIMIT 1;
                """,
                (fingerprint,),
            )
        return cur.fetchone() is not None


def _insert_event(
    conn,
    *,
    url: str | None,
    headline: str,
    source: str,
    symbols: list[str],
    category: str,
    impact_score: int,
    impact_level: str,
    first_seen_at: datetime,
    expires_at: datetime,
    fingerprint: str,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO news_events (
                url, headline, source, symbols, category, impact_score, impact_level,
                summary, headline_fingerprint, first_seen_at, expires_at, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """,
            (
                url,
                headline,
                source,
                ",".join(symbols) if symbols else "",
                category,
                int(impact_score),
                impact_level,
                fingerprint,
                first_seen_at,
                expires_at,
            ),
        )
    return True


def scan_alert_events() -> dict:
    result = {
        "ok": True,
        "fetched": 0,
        "inserted": 0,
        "duplicates": 0,
        "high": 0,
        "medium": 0,
    }
    if not is_database_configured():
        logger.error("Alerts scan: DATABASE_URL is not set on this server.")
        return {
            **result,
            "ok": False,
            "error": ERROR_DB_NOT_CONFIGURED,
            "detail": "DATABASE_URL is not set on the server; set it in the hosting environment.",
        }

    # Connect before fetching news so a database outage fails fast and does not
    # spend news API quota.
    try:
        conn = get_connection()
    except Exception as exc:
        logger.exception("Alerts scan: could not connect to the database.")
        return {
            **result,
            "ok": False,
            "error": ERROR_DB_UNAVAILABLE,
            "detail": (
                f"Could not connect to Postgres ({type(exc).__name__}). Check that DATABASE_URL "
                "points at a running database (see server logs for the full error)."
            ),
        }

    market = get_general_market_news(limit=25)
    crypto = get_general_crypto_news(limit=25)
    watchlist_terms = _watchlist_terms()
    now_utc = datetime.now(timezone.utc)
    ttl = timedelta(hours=max(1, settings.ALERT_EVENT_TTL_HOURS))

    try:
        for category, articles in (("market", market), ("crypto", crypto)):
            for article in articles:
                headline = str(article.get("headline", "")).strip()
                if not headline:
                    continue
                result["fetched"] += 1
                source = str(article.get("source", "")).strip()
                url_raw = str(article.get("url", "")).strip()
                url = url_raw if url_raw else None
                fingerprint = _headline_fingerprint(headline)

                if _event_exists(conn, url, fingerprint):
                    result["duplicates"] += 1
                    continue

                scored = score_news_event(
                    headline=headline,
                    source=source,
                    category=category,
                    watchlist_terms=watchlist_terms,
                )
                level = str(scored["impact_level"])
                if level not in {"high", "medium"}:
                    continue

                _insert_event(
                    conn,
                    url=url,
                    headline=headline,
                    source=source,
                    symbols=list(scored["matched_symbols"]),
                    category=str(scored["category"]),
                    impact_score=int(scored["impact_score"]),
                    impact_level=level,
                    first_seen_at=now_utc,
                    expires_at=now_utc + ttl,
                    fingerprint=fingerprint,
                )
                result["inserted"] += 1
                result[level] += 1

        conn.commit()
        return result
    except Exception as exc:
        logger.exception("Alerts scan: failed while processing news events.")
        conn.rollback()
        return {
            **result,
            "ok": False,
            "error": ERROR_SCAN_FAILED,
            "detail": f"Scan failed ({type(exc).__name__}); see server logs for the full error.",
        }
    finally:
        conn.close()


def get_saved_alert_events(hours: int = 24, limit: int = 10) -> dict:
    if not is_database_configured():
        return {
            "ok": False,
            "events": [],
            "error": "Alerts storage is not configured because DATABASE_URL is missing.",
        }

    bounded_hours = max(1, int(hours))
    bounded_limit = max(1, int(limit))
    since = datetime.now(timezone.utc) - timedelta(hours=bounded_hours)

    try:
        conn = get_connection()
    except Exception:
        return {"ok": False, "events": [], "error": "Could not read saved alerts right now."}

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT headline, source, url, symbols, category, impact_score, impact_level, first_seen_at
                FROM news_events
                WHERE expires_at > CURRENT_TIMESTAMP
                  AND first_seen_at >= %s
                  AND impact_level IN ('high', 'medium')
                ORDER BY
                  CASE WHEN impact_level = 'high' THEN 0 ELSE 1 END ASC,
                  impact_score DESC,
                  first_seen_at DESC
                LIMIT %s;
                """,
                (since, bounded_limit),
            )
            rows = cur.fetchall()

        events: list[dict] = []
        for row in rows:
            first_seen = row[7]
            if isinstance(first_seen, datetime):
                first_seen_text = first_seen.strftime("%Y-%m-%d %H:%M UTC")
            else:
                first_seen_text = str(first_seen)
            events.append(
                {
                    "headline": str(row[0] or ""),
                    "source": str(row[1] or ""),
                    "url": str(row[2] or ""),
                    "symbols": str(row[3] or ""),
                    "category": str(row[4] or ""),
                    "impact_score": int(row[5] or 0),
                    "impact_level": str(row[6] or "").lower(),
                    "first_seen_at": first_seen_text,
                }
            )
        return {"ok": True, "events": events, "error": ""}
    except Exception:
        return {"ok": False, "events": [], "error": "Could not read saved alerts right now."}
    finally:
        conn.close()
