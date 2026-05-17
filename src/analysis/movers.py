MOVE_THRESHOLD_STOCK = 2.0   # % — flag stocks moving more than this
MOVE_THRESHOLD_CRYPTO = 3.0  # % — crypto is noisier, higher bar
VOLUME_SPIKE_THRESHOLD = 1.5  # x average — flag unusual volume

# ── Multi-window thresholds by asset class ────────────────────────────────────

MAJOR_CRYPTO = {"BTC", "ETH"}

# Per-window significance thresholds (absolute %)
MOVE_THRESHOLDS: dict[str, dict[str, float]] = {
    "btc_eth":   {"1d": 2.0, "3d": 4.0, "7d": 6.0},
    "altcoin":   {"1d": 4.0, "3d": 8.0, "7d": 12.0},
    "large_cap": {"1d": 2.5, "3d": 5.0, "7d": 8.0},
    "etf":       {"1d": 1.0, "3d": 2.0, "7d": 3.0},
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
    thresholds = MOVE_THRESHOLDS.get(asset_class, MOVE_THRESHOLDS["large_cap"])

    m1d = moves.get("1d") or 0.0
    m3d = moves.get("3d") or 0.0
    m7d = moves.get("7d") or 0.0

    if abs(m1d) >= thresholds["1d"]:
        return "1d", f"1D move ({m1d:+.2f}%) exceeds {thresholds['1d']}% threshold"

    if abs(m3d) >= thresholds["3d"]:
        return "3d", (
            f"1D move is small ({m1d:+.2f}%); "
            f"3D move ({m3d:+.1f}%) exceeds {thresholds['3d']}% threshold"
        )

    if abs(m7d) >= thresholds["7d"]:
        return "7d", (
            f"1D ({m1d:+.2f}%) and 3D ({m3d:+.1f}%) moves are small; "
            f"7D move ({m7d:+.1f}%) exceeds {thresholds['7d']}% threshold"
        )

    return "none", (
        f"No significant move: 1D {m1d:+.2f}%, 3D {m3d:+.1f}%, 7D {m7d:+.1f}%"
    )


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
