MOVE_THRESHOLD_STOCK = 2.0   # % — flag stocks moving more than this
MOVE_THRESHOLD_CRYPTO = 3.0  # % — crypto is noisier, higher bar
VOLUME_SPIKE_THRESHOLD = 1.5  # x average — flag unusual volume

# ── Multi-window thresholds by asset class ────────────────────────────────────

MAJOR_CRYPTO = {"BTC", "ETH"}

# Per-window movement severity thresholds (absolute %)
# band: abs(move) < moderate => noise, < major => moderate, >= major => major
MOVE_BANDS: dict[str, dict[str, dict[str, float]]] = {
    "btc_eth": {
        "1d": {"moderate": 1.0, "major": 2.0},
        "3d": {"moderate": 2.5, "major": 4.0},
        "7d": {"moderate": 4.0, "major": 6.0},
        "30d": {"moderate": 6.0, "major": 10.0},
    },
    "altcoin": {
        "1d": {"moderate": 2.5, "major": 4.0},
        "3d": {"moderate": 4.0, "major": 8.0},
        "7d": {"moderate": 6.0, "major": 12.0},
        "30d": {"moderate": 10.0, "major": 20.0},
    },
    "large_cap": {
        "1d": {"moderate": 1.5, "major": 2.5},
        "3d": {"moderate": 3.0, "major": 5.0},
        "7d": {"moderate": 5.0, "major": 8.0},
        "30d": {"moderate": 10.0, "major": 20.0},
    },
    "etf": {
        "1d": {"moderate": 0.5, "major": 1.0},
        "3d": {"moderate": 1.0, "major": 2.0},
        "7d": {"moderate": 1.5, "major": 3.0},
        "30d": {"moderate": 3.0, "major": 6.0},
    },
}

# How many calendar days of news to fetch for each window
WINDOW_NEWS_DAYS: dict[str, int] = {
    "1d": 2,
    "3d": 4,
    "7d": 10,
    "none": 2,
}


def classify_asset(symbol: str, asset_type: str) -> str:
    """Map symbol + asset_type to one of: btc_eth, altcoin, large_cap, etf."""
    if asset_type == "etf":
        return "etf"
    if asset_type == "crypto":
        return "btc_eth" if symbol.upper() in MAJOR_CRYPTO else "altcoin"
    return "large_cap"


def select_explanation_window(
    moves: dict, asset_class: str
) -> tuple[str, str]:
    """
    Pick the most meaningful time window for the /why explanation.
    Returns (window, reason_string). Window is "1d", "3d", "7d", or "none".
    Checks windows in order: 1D first, then 3D, then 7D.
    """
    bands = MOVE_BANDS.get(asset_class, MOVE_BANDS["large_cap"])

    m1d = moves.get("1d") or 0.0
    m3d = moves.get("3d") or 0.0
    m7d = moves.get("7d") or 0.0
    m30d = moves.get("30d") or 0.0

    if abs(m1d) >= bands["1d"]["moderate"]:
        return "1d", (
            f"1D {classify_move(m1d, asset_class, '1d')} "
            f"{'strength' if m1d >= 0 else 'weakness'} ({m1d:+.2f}%)"
        )

    if abs(m3d) >= bands["3d"]["moderate"]:
        return "3d", (
            f"1D move is noise ({m1d:+.2f}%); "
            f"3D {classify_move(m3d, asset_class, '3d')} "
            f"{'strength' if m3d >= 0 else 'weakness'} ({m3d:+.1f}%)"
        )

    if abs(m7d) >= bands["7d"]["moderate"]:
        return "7d", (
            f"1D ({m1d:+.2f}%) and 3D ({m3d:+.1f}%) are noise; "
            f"7D {classify_move(m7d, asset_class, '7d')} "
            f"{'strength' if m7d >= 0 else 'weakness'} ({m7d:+.1f}%)"
        )

    if abs(m30d) >= bands["30d"]["moderate"]:
        return "30d", (
            f"Short-term moves are noise; "
            f"30D {classify_move(m30d, asset_class, '30d')} "
            f"{'strength' if m30d >= 0 else 'weakness'} ({m30d:+.1f}%)"
        )

    return "none", (
        f"Noise regime: 1D {m1d:+.2f}%, 3D {m3d:+.1f}%, 7D {m7d:+.1f}%, 30D {m30d:+.1f}%"
    )


def classify_move(move_pct: float | None, asset_class: str, window: str) -> str:
    """Return 'noise', 'moderate', or 'major' relative to per-class thresholds."""
    if move_pct is None:
        return "unknown"
    bands = MOVE_BANDS.get(asset_class, MOVE_BANDS["large_cap"])
    thresholds = bands.get(window, {"moderate": 2.5, "major": 4.0})
    if abs(move_pct) < thresholds["moderate"]:
        return "noise"
    if abs(move_pct) < thresholds["major"]:
        return "moderate"
    return "major"


def get_movement_severity(moves: dict, asset_class: str) -> dict:
    """Return severity labels for 1D/3D/7D/30D plus signed move values."""
    out: dict[str, dict] = {}
    for window in ("1d", "3d", "7d", "30d"):
        value = moves.get(window)
        out[window] = {
            "pct": value,
            "severity": classify_move(value, asset_class, window),
            "direction": (
                "strength" if (value is not None and value > 0)
                else "weakness" if (value is not None and value < 0)
                else "flat"
            ),
        }
    return out


def get_pullback_from_high_context(recent_context: dict) -> dict:
    """
    Classify pullback-from-high context using 7D/30D distance from recent highs.
    Distances are expected as negative percentages (current vs high).
    """
    d7 = recent_context.get("dist_from_7d_high_pct")
    d30 = recent_context.get("dist_from_30d_high_pct")

    def _bucket(distance: float | None, mild: float, moderate: float, sharp: float) -> str:
        if distance is None:
            return "none"
        below = abs(distance) if distance < 0 else 0.0
        if below >= sharp:
            return "sharp"
        if below >= moderate:
            return "moderate"
        if below >= mild:
            return "mild"
        return "none"

    b7 = _bucket(d7, mild=3.0, moderate=5.0, sharp=8.0)
    b30 = _bucket(d30, mild=4.0, moderate=7.0, sharp=12.0)

    # Prefer 7D framing for near-term context; fallback to 30D.
    if b7 != "none":
        primary = {"label": b7, "window": "7d", "distance_pct": d7}
    elif b30 != "none":
        primary = {"label": b30, "window": "30d", "distance_pct": d30}
    else:
        primary = {"label": "none", "window": None, "distance_pct": None}

    return {
        "from_7d_high": {"distance_pct": d7, "pullback": b7},
        "from_30d_high": {"distance_pct": d30, "pullback": b30},
        "primary_pullback": primary,
    }


def build_trend_summary_line(symbol: str, moves: dict, recent_context: dict, asset_class: str) -> str:
    """Build concise pre-analysis trend line with severity or pullback framing."""
    pullback = get_pullback_from_high_context(recent_context).get("primary_pullback", {})
    label = pullback.get("label")
    p_window = pullback.get("window")
    p_dist = pullback.get("distance_pct")
    if label in ("mild", "moderate", "sharp") and p_window in ("7d", "30d") and p_dist is not None:
        return (
            f"Trend: {label} pullback from recent high — "
            f"{symbol} {p_dist:+.1f}% from {p_window.upper()} high"
        )

    for window in ("1d", "3d", "7d", "30d"):
        value = moves.get(window)
        severity = classify_move(value, asset_class, window)
        if value is None or severity == "noise":
            continue
        direction = "strength" if value > 0 else "weakness"
        return (
            f"Trend: {window.upper()} {severity} {direction} — "
            f"{symbol} {value:+.1f}% over {window.upper()}"
        )

    return "Trend: noise regime — no moderate or major move detected"


def get_recent_trend(moves: dict) -> str:
    """
    Classify the broader recent trend from multi-window moves.
    Returns a compact label the LLM can use as narrative context.
    Checks pullback/bounce conditions before trend continuation to avoid
    mislabeling a down-day inside a strong uptrend as "strong_uptrend".
    """
    m1d = moves.get("1d") or 0.0
    m7d = moves.get("7d") or 0.0
    m30d = moves.get("30d") or 0.0

    if m30d >= 8:
        if m1d < -1.0:
            return "pullback_from_strong_uptrend"
        if m7d < -1.5:
            return "cooling_after_strong_rally"
        if m7d >= 2:
            return "strong_uptrend"
        return "consolidating_after_strong_rally"
    if m30d >= 3:
        if m1d < -2:
            return "pullback_in_rally"
        return "mild_uptrend" if m7d >= 1 else "cooling_after_rally"
    if m30d <= -8:
        if m1d > 2:
            return "bounce_in_downtrend"
        if m7d <= -2:
            return "strong_downtrend"
        return "consolidating_in_downtrend"
    if m30d <= -3:
        if m1d > 2:
            return "bounce_in_decline"
        return "mild_downtrend" if m7d <= -1 else "stabilizing_after_decline"
    if m7d >= 3:
        return "short_term_up"
    if m7d <= -3:
        return "short_term_down"
    return "sideways"


def is_meaningful_mover(
    change_pct: float,
    vol_ratio: float | None = None,
    is_crypto: bool = False,
) -> bool:
    """Return True if the asset's move or volume warrants including in the brief."""
    threshold = MOVE_THRESHOLD_CRYPTO if is_crypto else MOVE_THRESHOLD_STOCK
    if abs(change_pct) >= threshold:
        return True
    if vol_ratio is not None and vol_ratio >= VOLUME_SPIKE_THRESHOLD:
        return True
    return False


def get_technical_events(technicals: dict) -> list[str]:
    """Derive human-readable technical event strings from computed levels."""
    events = []

    if technicals.get("broke_20d_high"):
        events.append("broke above 20-day high")
    if technicals.get("broke_20d_low"):
        events.append("broke below 20-day low")

    vs_ma50 = technicals.get("vs_ma50_pct")
    if vs_ma50 is not None:
        if abs(vs_ma50) <= 0.5:
            events.append("testing 50-day MA")
        elif vs_ma50 < 0:
            events.append(f"below 50-day MA ({vs_ma50:+.1f}%)")

    vs_ma200 = technicals.get("vs_ma200_pct")
    if vs_ma200 is not None:
        if abs(vs_ma200) <= 0.5:
            events.append("testing 200-day MA")
        elif vs_ma200 < 0:
            events.append(f"below 200-day MA ({vs_ma200:+.1f}%)")

    vol_ratio = technicals.get("volume_ratio_20d")
    if vol_ratio is not None and vol_ratio >= VOLUME_SPIKE_THRESHOLD:
        events.append(f"volume {vol_ratio:.1f}x 20-day avg")

    return events


def rank_movers(assets: list[dict]) -> list[dict]:
    """Sort by absolute % move, largest first."""
    return sorted(assets, key=lambda x: abs(x.get("change_pct", 0)), reverse=True)
