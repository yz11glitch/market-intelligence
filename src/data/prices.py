import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Optional


def _yf_symbol(symbol: str, is_crypto: bool) -> str:
    if is_crypto and not symbol.endswith("-USD"):
        return f"{symbol}-USD"
    return symbol


def fetch_ohlcv(symbol: str, is_crypto: bool = False, days: int = 210) -> Optional[pd.DataFrame]:
    """Fetch OHLCV history via yfinance Ticker.history(). Returns None on failure."""
    try:
        yf_sym = _yf_symbol(symbol, is_crypto)
        ticker = yf.Ticker(yf_sym)
        df = ticker.history(period=f"{days}d")
        if df.empty:
            return None
        # Drop timezone info from index for consistent handling
        df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
        return df
    except Exception as e:
        print(f"  [prices] Failed to fetch {symbol}: {e}")
        return None


def get_price_summary(symbol: str, is_crypto: bool = False) -> Optional[dict]:
    """Return today's price, previous close, and 1d change."""
    df = fetch_ohlcv(symbol, is_crypto=is_crypto, days=5)
    if df is None or len(df) < 2:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    current_price = float(latest["Close"])
    prev_close = float(prev["Close"])
    change_pct = ((current_price - prev_close) / prev_close) * 100

    result: dict = {
        "symbol": symbol,
        "price": round(current_price, 4),
        "prev_close": round(prev_close, 4),
        "change_pct": round(change_pct, 2),
        "date": str(df.index[-1].date()),
    }

    if "Volume" in df.columns and float(latest["Volume"]) > 0:
        result["volume"] = float(latest["Volume"])

    return result
