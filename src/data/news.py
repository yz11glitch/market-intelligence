from datetime import datetime, timedelta
from typing import Optional
from src.config.settings import settings
from src.data.crypto import get_crypto_info


def _finnhub_client():
    if not settings.FINNHUB_API_KEY:
        return None
    try:
        import finnhub
        return finnhub.Client(api_key=settings.FINNHUB_API_KEY)
    except ImportError:
        return None


def _format_article(article: dict) -> dict:
    ts = article.get("datetime", 0)
    published = (
        datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        if ts
        else ""
    )
    return {
        "headline": article.get("headline", "").strip(),
        "source": article.get("source", ""),
        "url": article.get("url", ""),
        "published": published,
    }


def get_stock_news(symbol: str, days_back: int = 2, limit: int = 5) -> list[dict]:
    """Fetch recent ticker-specific news from Finnhub."""
    client = _finnhub_client()
    if not client:
        return []
    try:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        articles = client.company_news(symbol, _from=from_date, to=to_date)
        return [_format_article(a) for a in articles[:limit]]
    except Exception as e:
        print(f"  [news] Stock news error for {symbol}: {e}")
        return []


def get_crypto_news(symbol: str, days_back: int = 3, limit: int = 5) -> list[dict]:
    """Fetch crypto news from Finnhub general crypto feed, filtered by coin and date."""
    client = _finnhub_client()
    if not client:
        return []
    try:
        articles = client.general_news("crypto", min_id=0)
        search_terms = get_crypto_info(symbol)["terms"]
        cutoff_ts = (datetime.now() - timedelta(days=days_back)).timestamp()

        relevant = []
        for article in articles:
            ts = article.get("datetime", 0)
            if ts and ts < cutoff_ts:
                continue
            text = (
                article.get("headline", "") + " " + article.get("summary", "")
            ).lower()
            if any(term in text for term in search_terms):
                relevant.append(_format_article(article))

        return relevant[:limit]
    except Exception as e:
        print(f"  [news] Crypto news error for {symbol}: {e}")
        return []


def get_upcoming_earnings(watchlist_symbols: list[str], days_ahead: int = 7) -> list[dict]:
    """Fetch earnings calendar from Finnhub, filtered to watchlist symbols."""
    client = _finnhub_client()
    if not client:
        return []
    try:
        from_date = datetime.now().strftime("%Y-%m-%d")
        to_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        cal = client.earnings_calendar(
            _from=from_date, to=to_date, symbol="", international=False
        )
        events = cal.get("earningsCalendar", [])
        watchlist_set = set(watchlist_symbols)
        return [
            {
                "symbol": e.get("symbol"),
                "date": e.get("date"),
                "eps_estimate": e.get("epsEstimate"),
            }
            for e in events
            if e.get("symbol") in watchlist_set
        ]
    except Exception as e:
        print(f"  [news] Earnings calendar error: {e}")
        return []
