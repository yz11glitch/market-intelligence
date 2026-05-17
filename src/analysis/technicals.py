import pandas as pd
from typing import Optional


def calculate_technicals(df: Optional[pd.DataFrame]) -> dict:
    """
    Compute technical levels from an OHLCV DataFrame.
    Requires at least 20 rows. Returns empty dict if data is insufficient.
    """
    if df is None or len(df) < 20:
        return {}

    close = df["Close"].astype(float)
    n = len(close)
    current = float(close.iloc[-1])

    result: dict = {"current_price": current}

    # --- 20-day high / low ---
    # Use the 20 days *excluding today* to detect genuine breaks
    window_20 = close.iloc[-21:-1] if n >= 21 else close.iloc[:-1]
    high_20d = float(window_20.max())
    low_20d = float(window_20.min())
    result["high_20d"] = round(high_20d, 4)
    result["low_20d"] = round(low_20d, 4)
    result["broke_20d_high"] = current > high_20d
    result["broke_20d_low"] = current < low_20d

    # --- Moving averages ---
    if n >= 50:
        ma50 = float(close.rolling(50).mean().iloc[-1])
        result["ma50"] = round(ma50, 4)
        result["vs_ma50_pct"] = round(((current - ma50) / ma50) * 100, 2)

    if n >= 200:
        ma200 = float(close.rolling(200).mean().iloc[-1])
        result["ma200"] = round(ma200, 4)
        result["vs_ma200_pct"] = round(((current - ma200) / ma200) * 100, 2)

    # --- 5-day swing high / low ---
    if n >= 5:
        result["swing_high_5d"] = round(float(close.tail(5).max()), 4)
        result["swing_low_5d"] = round(float(close.tail(5).min()), 4)

    # --- Volume ratio vs 20-day average ---
    if "Volume" in df.columns:
        volume = df["Volume"].astype(float)
        today_vol = float(volume.iloc[-1])
        if today_vol > 0 and n >= 20:
            avg_vol_20d = float(volume.tail(21).head(20).mean())  # exclude today
            if avg_vol_20d > 0:
                result["volume_ratio_20d"] = round(today_vol / avg_vol_20d, 2)

    return result


def calculate_multi_window_moves(df: "Optional[pd.DataFrame]") -> dict:
    """
    Compute % moves across 1D/3D/7D/30D windows and recent high/low context.
    All windows use trading days (yfinance data only contains trading days).
    Returns {"moves": {...}, "recent_context": {...}}, or {} if insufficient data.
    """
    if df is None or len(df) < 2:
        return {}

    close = df["Close"].astype(float)
    n = len(close)
    current = float(close.iloc[-1])

    def _pct(n_days_back: int) -> "float | None":
        # close.iloc[-1] vs close.iloc[-(n_days_back+1)]
        idx = n_days_back + 1
        if idx > n:
            return None
        ref = float(close.iloc[-idx])
        return round(((current - ref) / ref) * 100, 2) if ref > 0 else None

    moves = {
        "1d": _pct(1),
        "3d": _pct(3),
        "7d": _pct(7),
        "30d": _pct(30),
    }

    # Recent high/low windows (include today)
    w7 = close.tail(min(7, n))
    w30 = close.tail(min(30, n))
    high_7d = float(w7.max())
    low_7d = float(w7.min())
    high_30d = float(w30.max())
    low_30d = float(w30.min())

    recent_context = {
        "high_7d": round(high_7d, 4),
        "low_7d": round(low_7d, 4),
        "dist_from_7d_high_pct": round(((current - high_7d) / high_7d) * 100, 2),
        "dist_from_7d_low_pct": round(((current - low_7d) / low_7d) * 100, 2),
        "high_30d": round(high_30d, 4),
        "low_30d": round(low_30d, 4),
        "dist_from_30d_high_pct": round(((current - high_30d) / high_30d) * 100, 2),
        "dist_from_30d_low_pct": round(((current - low_30d) / low_30d) * 100, 2),
    }

    return {"moves": moves, "recent_context": recent_context}
