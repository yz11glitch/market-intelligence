from typing import Optional
from src.data.prices import fetch_ohlcv, get_price_summary

# Canonical symbol → human name and news search terms
CRYPTO_REGISTRY: dict[str, dict] = {
    "BTC": {"name": "Bitcoin", "terms": ["bitcoin", "btc"]},
    "ETH": {"name": "Ethereum", "terms": ["ethereum", "eth"]},
    "SOL": {"name": "Solana", "terms": ["solana", "sol"]},
    "BNB": {"name": "BNB", "terms": ["bnb", "binance coin"]},
    "XRP": {"name": "XRP", "terms": ["xrp", "ripple"]},
    "DOGE": {"name": "Dogecoin", "terms": ["dogecoin", "doge"]},
    "ADA": {"name": "Cardano", "terms": ["cardano", "ada"]},
    "AVAX": {"name": "Avalanche", "terms": ["avalanche", "avax"]},
    "MATIC": {"name": "Polygon", "terms": ["polygon", "matic"]},
    "DOT": {"name": "Polkadot", "terms": ["polkadot", "dot"]},
}


def is_crypto(symbol: str) -> bool:
    return symbol.upper() in CRYPTO_REGISTRY


def get_crypto_info(symbol: str) -> dict:
    return CRYPTO_REGISTRY.get(symbol.upper(), {"name": symbol, "terms": [symbol.lower()]})


def get_crypto_summary(symbol: str) -> Optional[dict]:
    """Price summary for crypto, including 7-day move."""
    symbol = symbol.upper()
    summary = get_price_summary(symbol, is_crypto=True)
    if summary is None:
        return None

    summary["name"] = get_crypto_info(symbol)["name"]
    summary["is_crypto"] = True

    # 7-day move: need at least 9 trading rows
    df = fetch_ohlcv(symbol, is_crypto=True, days=12)
    if df is not None and len(df) >= 8:
        price_7d_ago = float(df.iloc[-8]["Close"])
        current = summary["price"]
        if price_7d_ago > 0:
            summary["change_7d_pct"] = round(
                ((current - price_7d_ago) / price_7d_ago) * 100, 2
            )

    return summary
