from src.analysis.movers import (
    get_technical_events, classify_move, get_recent_trend,
    get_movement_severity, get_pullback_from_high_context,
)
from src.utils.formatting import fmt_price


def build_asset_facts(
    symbol: str,
    asset_type: str,
    price_summary: dict,
    technicals: dict,
    news: list[dict],
    change_7d_pct: float | None = None,
    # ── why-command enrichment (optional) ──
    multi_window: dict | None = None,
    explanation_window: str | None = None,
    window_reason: str | None = None,
    asset_class: str | None = None,
) -> dict:
    """
    Assemble a structured facts object to pass to the LLM.
    The LLM receives only what is in this dict — no open-ended retrieval.
    multi_window / explanation_window are populated for /why, omitted for brief.
    """
    from src.utils.formatting import fmt_pct  # local import to avoid circular dep
    facts: dict = {
        "symbol": symbol,
        "asset_type": asset_type,
        "current_price": price_summary.get("price"),
        "price": price_summary.get("price"),
        "formatted_price": fmt_price(price_summary.get("price")),
        "change_pct_1d": price_summary.get("change_pct"),
        "formatted_change_pct": fmt_pct(price_summary.get("change_pct")),
        "technical_events": get_technical_events(technicals),
        "news": news,
    }

    # Legacy key kept so brief command works unchanged
    facts["change_pct"] = facts["change_pct_1d"]

    if change_7d_pct is not None:
        facts["change_7d_pct"] = change_7d_pct

    # Key technical levels the LLM can reference
    for key in ("vs_ma50_pct", "vs_ma200_pct", "volume_ratio_20d",
                "broke_20d_high", "broke_20d_low"):
        if key in technicals:
            facts[key] = technicals[key]

    # Multi-window enrichment (used by why and brief when provided)
    if multi_window:
        moves = multi_window.get("moves", {})
        recent_context = multi_window.get("recent_context", {})
        facts["moves"] = moves
        facts["recent_context"] = recent_context
        if asset_class is not None:
            movement_severity = get_movement_severity(moves, asset_class)
            primary_window = "none"
            for w in ("1d", "3d", "7d", "30d"):
                if movement_severity.get(w, {}).get("severity") in ("moderate", "major"):
                    primary_window = w
                    break
            facts["movement_severity"] = movement_severity
            facts["brief_guidance"] = {
                "is_1d_noise": movement_severity.get("1d", {}).get("severity") == "noise",
                "direct_causality_allowed_for_1d": movement_severity.get("1d", {}).get("severity") != "noise",
                "primary_window": primary_window,
            }
        facts["pullback_context"] = get_pullback_from_high_context(recent_context)

    # Technical snapshot for concise multi-timeframe summaries
    facts["technicals"] = {
        "ma50": technicals.get("ma50"),
        "ma200": technicals.get("ma200"),
        "vs_ma50_pct": technicals.get("vs_ma50_pct"),
        "vs_ma200_pct": technicals.get("vs_ma200_pct"),
        "high_20d": technicals.get("high_20d"),
        "low_20d": technicals.get("low_20d"),
        "broke_20d_high": technicals.get("broke_20d_high"),
        "broke_20d_low": technicals.get("broke_20d_low"),
        "volume_ratio_20d": technicals.get("volume_ratio_20d"),
    }

    if explanation_window is not None:
        facts["explanation_window"] = explanation_window
    if window_reason is not None:
        facts["window_reason"] = window_reason
    if asset_class is not None:
        facts["asset_class"] = asset_class

    return facts


def build_why_facts(
    symbol: str,
    asset_type: str,
    asset_class: str,
    price_summary: dict,
    technicals: dict,
    multi_window: dict,
    explanation_window: str,
    window_reason: str,
    news_by_window: dict,
    market_context: dict,
    upcoming_events: list[dict],
) -> dict:
    """
    Enriched facts object for /why command.
    News is pre-bucketed into time windows so the LLM cannot accidentally use
    7D bullish news to explain a negative 1D move.
    """
    moves = multi_window.get("moves", {})
    recent_context = multi_window.get("recent_context", {})
    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "asset_class": asset_class,
        "current_price": price_summary.get("price"),
        "moves": moves,
        "movement_severity": get_movement_severity(moves, asset_class),
        "move_classification": {
            "1d": classify_move(moves.get("1d"), asset_class, "1d"),
            "3d": classify_move(moves.get("3d"), asset_class, "3d"),
            "7d": classify_move(moves.get("7d"), asset_class, "7d"),
            "30d": classify_move(moves.get("30d"), asset_class, "30d"),
        },
        "recent_trend": get_recent_trend(moves),
        "recent_context": recent_context,
        "pullback_context": get_pullback_from_high_context(recent_context),
        "explanation_window": explanation_window,
        "window_reason": window_reason,
        "technicals": {
            "ma50": technicals.get("ma50"),
            "ma200": technicals.get("ma200"),
            "vs_ma50_pct": technicals.get("vs_ma50_pct"),
            "vs_ma200_pct": technicals.get("vs_ma200_pct"),
            "high_20d": technicals.get("high_20d"),
            "low_20d": technicals.get("low_20d"),
            "broke_20d_high": technicals.get("broke_20d_high"),
            "broke_20d_low": technicals.get("broke_20d_low"),
            "volume_ratio_20d": technicals.get("volume_ratio_20d"),
            "technical_events": get_technical_events(technicals),
        },
        "news_by_window": news_by_window,
        "market_context": market_context,
        "upcoming_events": upcoming_events,
    }
