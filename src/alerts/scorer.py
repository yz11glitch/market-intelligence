import re

from src.config.settings import settings

_MACRO_TERMS = (
    "fed",
    "cpi",
    "inflation",
    "jobs",
    "yield",
    "yields",
    "rate decision",
    "recession",
    "fomc",
    "powell",
)
_EARNINGS_TERMS = (
    "earnings",
    "guidance",
    "downgrade",
    "upgrade",
    "eps",
    "revenue miss",
    "revenue beat",
)
_CRYPTO_TERMS = (
    "etf approval",
    "etf inflow",
    "etf outflow",
    "inflow",
    "outflow",
    "liquidation",
    "sec",
    "regulation",
    "stablecoin",
    "exchange hack",
)
_MAJOR_RISK_TERMS = (
    "war",
    "sanctions",
    "export restriction",
    "lawsuit",
    "doj",
    "sec",
    "bankruptcy",
    "hack",
)
_SPECULATIVE_TERMS = ("rumor", "could", "may", "opinion", "prediction")
_TRUSTED_SOURCES = {
    "reuters",
    "bloomberg",
    "wall street journal",
    "financial times",
    "cnbc",
    "coindesk",
    "cointelegraph",
}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _find_watchlist_matches(headline_lower: str, watchlist_terms: list[str]) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for term in watchlist_terms:
        normalized = term.strip()
        if not normalized:
            continue
        key = normalized.upper()
        if key in seen:
            continue
        pattern = rf"\b{re.escape(normalized.lower())}\b"
        if re.search(pattern, headline_lower):
            seen.add(key)
            matches.append(key)
    return matches


def score_news_event(
    headline: str,
    source: str,
    category: str,
    watchlist_terms: list[str] | None = None,
) -> dict:
    headline_lower = headline.lower()
    source_lower = source.lower().strip()
    watchlist_matches = _find_watchlist_matches(headline_lower, watchlist_terms or [])

    score = 1
    reasons: list[str] = []
    if watchlist_matches:
        score += 3
        reasons.append("watchlist symbol/company mention")

    if _contains_any(headline_lower, _MACRO_TERMS):
        score += 3
        reasons.append("macro term")

    if _contains_any(headline_lower, _EARNINGS_TERMS):
        score += 3
        reasons.append("earnings/guidance/analyst term")

    if _contains_any(headline_lower, _CRYPTO_TERMS):
        score += 3
        reasons.append("crypto market structure/regulation term")

    if _contains_any(headline_lower, _MAJOR_RISK_TERMS):
        score += 3
        reasons.append("major risk/legal/geopolitical term")

    if any(name in source_lower for name in _TRUSTED_SOURCES):
        score += 2
        reasons.append("trusted source")

    if _contains_any(headline_lower, _SPECULATIVE_TERMS):
        score -= 2
        reasons.append("speculative wording penalty")

    score = max(1, min(10, score))
    if score >= settings.ALERT_SCORE_THRESHOLD:
        level = "high"
    elif score >= settings.ALERT_MEDIUM_THRESHOLD:
        level = "medium"
    else:
        level = "low"

    return {
        "impact_score": score,
        "impact_level": level,
        "matched_symbols": watchlist_matches,
        "matched_reasons": reasons,
        "category": category,
    }
