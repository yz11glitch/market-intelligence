from src.analysis.movers import get_technical_events


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
    facts: dict = {
        "symbol": symbol,
        "asset_type": asset_type,
        "current_price": price_summary.get("price"),
        "change_pct_1d": price_summary.get("change_pct"),
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

    # Multi-window enrichment (why command only)
    if multi_window:
        facts["moves"] = multi_window.get("moves", {})
        facts["recent_context"] = multi_window.get("recent_context", {})

    if explanation_window is not None:
        facts["explanation_window"] = explanation_window
    if window_reason is not None:
        facts["window_reason"] = window_reason
    if asset_class is not None:
        facts["asset_class"] = asset_class

    return facts
