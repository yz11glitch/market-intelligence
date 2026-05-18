from datetime import datetime, timedelta
from typing import Optional
from src.config.settings import settings
from src.data.crypto import get_crypto_info

_NEWS_BUCKET_KEYS = ("recent_1d", "recent_3d", "recent_7d", "recent_30d")
_NEWS_CACHE_TTL = timedelta(minutes=30)
_multi_window_news_cache: dict[str, dict] = {}


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


def _empty_news_buckets() -> dict[str, list]:
    return {k: [] for k in _NEWS_BUCKET_KEYS}


def _clean_news_buckets(news_by_window: dict) -> dict[str, list]:
    return {k: list(news_by_window.get(k, [])) for k in _NEWS_BUCKET_KEYS}


def _news_cache_key(kind: str, symbol: str) -> str:
    return f"{kind}:{symbol.upper()}"


def _cache_set_news(cache_key: str, news_by_window: dict) -> None:
    _multi_window_news_cache[cache_key] = {
        "expires_at": datetime.now() + _NEWS_CACHE_TTL,
        "news_by_window": _clean_news_buckets(news_by_window),
    }


def _cache_get_news(cache_key: str) -> dict[str, list] | None:
    cached = _multi_window_news_cache.get(cache_key)
    if not cached:
        return None
    if cached.get("expires_at") < datetime.now():
        _multi_window_news_cache.pop(cache_key, None)
        return None
    return _clean_news_buckets(cached.get("news_by_window", {}))


def _is_rate_limited_error(error: Exception) -> bool:
    text = str(error).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


def _with_news_meta(
    news_by_window: dict[str, list],
    *,
    rate_limited: bool,
    used_cache: bool,
    error: str | None = None,
) -> dict:
    result = _clean_news_buckets(news_by_window)
    if rate_limited or used_cache:
        result["_meta"] = {
            "rate_limited": rate_limited,
            "used_cache": used_cache,
            "error": error or "",
        }
    return result


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


def get_stock_news_multi_window(symbol: str) -> dict:
    """
    Fetch up to 30 days of stock news in one API call and bucket by recency.
    Returns: {recent_1d, recent_3d, recent_7d, recent_30d}
    Buckets are mutually exclusive; use matching bucket per timeframe section.
    """
    client = _finnhub_client()
    empty = _empty_news_buckets()
    cache_key = _news_cache_key("stock", symbol)
    if not client:
        return empty
    now = datetime.now()
    try:
        articles = client.company_news(
            symbol,
            _from=(now - timedelta(days=30)).strftime("%Y-%m-%d"),
            to=now.strftime("%Y-%m-%d"),
        )
    except Exception as e:
        rate_limited = _is_rate_limited_error(e)
        print(f"  [news] Multi-window news error for {symbol}: {e}")
        cached = _cache_get_news(cache_key)
        if cached is not None:
            print(f"  [news] Using cached stock news for {symbol} (ttl=30m).")
            return _with_news_meta(cached, rate_limited=rate_limited, used_cache=True, error=str(e))
        if rate_limited:
            print(f"  [news] Stock news rate-limited for {symbol}; continuing with price/context only.")
        return _with_news_meta(empty, rate_limited=rate_limited, used_cache=False, error=str(e))

    cutoff_1d = (now - timedelta(days=2)).timestamp()
    cutoff_3d = (now - timedelta(days=4)).timestamp()
    cutoff_7d = (now - timedelta(days=10)).timestamp()
    buckets: dict[str, list] = _empty_news_buckets()

    for article in articles[:50]:
        ts = article.get("datetime", 0)
        fmt = _format_article(article)
        if ts >= cutoff_1d:
            buckets["recent_1d"].append(fmt)
        elif ts >= cutoff_3d:
            buckets["recent_3d"].append(fmt)
        elif ts >= cutoff_7d:
            buckets["recent_7d"].append(fmt)
        else:
            buckets["recent_30d"].append(fmt)

    result = {k: v[:8] for k, v in buckets.items()}
    _cache_set_news(cache_key, result)
    return result


def get_crypto_news_multi_window(symbol: str) -> dict:
    """
    Fetch crypto news from Finnhub general feed and bucket into time windows.
    general_news typically covers only the last few days, so recent_30d is usually empty.
    """
    client = _finnhub_client()
    empty = _empty_news_buckets()
    cache_key = _news_cache_key("crypto", symbol)
    if not client:
        return empty
    try:
        articles = client.general_news("crypto", min_id=0)
    except Exception as e:
        rate_limited = _is_rate_limited_error(e)
        print(f"  [news] Crypto multi-window news error for {symbol}: {e}")
        cached = _cache_get_news(cache_key)
        if cached is not None:
            print(f"  [news] Using cached crypto news for {symbol} (ttl=30m).")
            return _with_news_meta(cached, rate_limited=rate_limited, used_cache=True, error=str(e))
        if rate_limited:
            print(f"  [news] Crypto news rate-limited for {symbol}; continuing with price/context only.")
        return _with_news_meta(empty, rate_limited=rate_limited, used_cache=False, error=str(e))

    search_terms = get_crypto_info(symbol)["terms"]
    now = datetime.now()
    cutoff_1d = (now - timedelta(days=2)).timestamp()
    cutoff_3d = (now - timedelta(days=4)).timestamp()
    cutoff_7d = (now - timedelta(days=10)).timestamp()
    buckets: dict[str, list] = _empty_news_buckets()

    for article in articles:
        ts = article.get("datetime", 0)
        if ts < cutoff_7d:
            continue
        text = (article.get("headline", "") + " " + article.get("summary", "")).lower()
        if not any(term in text for term in search_terms):
            continue
        fmt = _format_article(article)
        if ts >= cutoff_1d:
            buckets["recent_1d"].append(fmt)
        elif ts >= cutoff_3d:
            buckets["recent_3d"].append(fmt)
        else:
            buckets["recent_7d"].append(fmt)

    result = {k: v[:8] for k, v in buckets.items()}
    _cache_set_news(cache_key, result)
    return result


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


def get_general_market_news(limit: int = 10) -> list[dict]:
    """Fetch unfiltered general stock market news from Finnhub."""
    client = _finnhub_client()
    if not client:
        return []
    try:
        articles = client.general_news("general", min_id=0)
        return [_format_article(a) for a in articles[:limit]]
    except Exception as e:
        print(f"  [news] General market news error: {e}")
        return []


def get_general_crypto_news(limit: int = 10) -> list[dict]:
    """Fetch unfiltered general crypto market news from Finnhub."""
    client = _finnhub_client()
    if not client:
        return []
    try:
        articles = client.general_news("crypto", min_id=0)
        return [_format_article(a) for a in articles[:limit]]
    except Exception as e:
        print(f"  [news] General crypto news error: {e}")
        return []
