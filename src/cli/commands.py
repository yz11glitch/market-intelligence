import pathlib
import yaml
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.data.prices import fetch_ohlcv, get_price_summary
from src.data.crypto import is_crypto, get_crypto_summary
from src.data.news import get_stock_news, get_crypto_news, get_upcoming_earnings
from src.analysis.technicals import calculate_technicals, calculate_multi_window_moves
from src.analysis.movers import (
    is_meaningful_mover, rank_movers,
    classify_asset, select_explanation_window, WINDOW_NEWS_DAYS,
)
from src.analysis.facts import build_asset_facts
from src.ai.client import complete
from src.ai.prompts import SYSTEM_BRIEF, SYSTEM_WHY, build_brief_prompt, build_why_prompt
from src.utils.formatting import (
    fmt_pct, print_header, print_section, separator, levels_table
)

ROOT = pathlib.Path(__file__).parent.parent.parent
WATCHLIST_PATH = ROOT / "config" / "watchlist.yaml"


def _load_watchlist() -> dict:
    with open(WATCHLIST_PATH) as f:
        return yaml.safe_load(f)


# ── Data fetch helpers (called in parallel) ──────────────────────────────────

def _fetch_stock(symbol: str, asset_type: str = "stock") -> tuple[str, dict | None]:
    df = fetch_ohlcv(symbol, is_crypto=False, days=210)
    summary = get_price_summary(symbol, is_crypto=False)
    if df is None or summary is None:
        return symbol, None
    summary["technicals"] = calculate_technicals(df)
    summary["asset_type"] = asset_type
    return symbol, summary


def _fetch_crypto(symbol: str) -> tuple[str, dict | None]:
    df = fetch_ohlcv(symbol, is_crypto=True, days=210)
    summary = get_crypto_summary(symbol)
    if df is None or summary is None:
        return symbol, None
    summary["technicals"] = calculate_technicals(df)
    summary["asset_type"] = "crypto"
    return symbol, summary


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_brief() -> None:
    watchlist = _load_watchlist()
    stocks = watchlist.get("stocks", [])
    etfs = watchlist.get("etfs", [])
    crypto_list = watchlist.get("crypto", [])

    print("\nFetching market data...")

    # Parallel data fetch for all assets
    results: dict[str, dict] = {}
    futures = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for sym in stocks:
            futures[pool.submit(_fetch_stock, sym, "stock")] = sym
        for sym in etfs:
            futures[pool.submit(_fetch_stock, sym, "etf")] = sym
        for sym in crypto_list:
            futures[pool.submit(_fetch_crypto, sym)] = sym

        for future in as_completed(futures):
            sym, data = future.result()
            if data:
                results[sym] = data

    fetched = len(results)
    total = len(stocks) + len(etfs) + len(crypto_list)
    print(f"Fetched {fetched}/{total} assets. Filtering movers...")

    # Index snapshot (always included, no threshold)
    index_facts = []
    for sym in etfs:
        if sym in results:
            d = results[sym]
            index_facts.append({
                "symbol": sym,
                "price": d["price"],
                "change_pct": d["change_pct"],
            })

    # Stock movers
    stock_movers = []
    for sym in stocks:
        if sym not in results:
            continue
        d = results[sym]
        tech = d["technicals"]
        vol_ratio = tech.get("volume_ratio_20d")
        if is_meaningful_mover(d["change_pct"], vol_ratio, is_crypto=False):
            news = get_stock_news(sym)
            stock_movers.append(
                build_asset_facts(sym, "stock", d, tech, news)
            )
    stock_movers = rank_movers(stock_movers)[:6]

    # Crypto (always include all watchlist crypto)
    crypto_facts = []
    for sym in crypto_list:
        if sym not in results:
            continue
        d = results[sym]
        tech = d["technicals"]
        news = get_crypto_news(sym)
        crypto_facts.append(
            build_asset_facts(
                sym, "crypto", d, tech, news,
                change_7d_pct=d.get("change_7d_pct"),
            )
        )

    # Upcoming earnings for watchlist stocks
    events = get_upcoming_earnings(stocks, days_ahead=7)

    print("Generating brief...\n")
    prompt = build_brief_prompt(index_facts, stock_movers, crypto_facts, events)
    brief = complete(prompt, SYSTEM_BRIEF)

    print_header(f"MARKET BRIEF — {datetime.now().strftime('%Y-%m-%d')}")
    print(brief)
    print(separator("═"))


def cmd_why(symbol: str) -> None:
    crypto_asset = is_crypto(symbol)
    print(f"\nAnalyzing {symbol}...")

    if crypto_asset:
        df = fetch_ohlcv(symbol, is_crypto=True, days=210)
        summary = get_crypto_summary(symbol)
        asset_type = "crypto"
    else:
        df = fetch_ohlcv(symbol, is_crypto=False, days=210)
        summary = get_price_summary(symbol, is_crypto=False)
        asset_type = "stock"

    if df is None or summary is None:
        print(f"No data available for {symbol}.")
        return

    technicals = calculate_technicals(df)
    multi_window = calculate_multi_window_moves(df)

    # Determine which window is the meaningful signal
    asset_class = classify_asset(symbol, asset_type)
    window, window_reason = select_explanation_window(
        multi_window.get("moves", {}), asset_class
    )
    news_days = WINDOW_NEWS_DAYS.get(window, 2)

    print(f"  Window: {window} ({window_reason[:60]}...)" if len(window_reason) > 60
          else f"  Window: {window} — {window_reason}")

    # Fetch news aligned to the selected window
    if crypto_asset:
        news = get_crypto_news(symbol, days_back=news_days)
    else:
        news = get_stock_news(symbol, days_back=news_days)

    facts = build_asset_facts(
        symbol, asset_type, summary, technicals, news,
        change_7d_pct=summary.get("change_7d_pct"),
        multi_window=multi_window,
        explanation_window=window,
        window_reason=window_reason,
        asset_class=asset_class,
    )

    prompt = build_why_prompt(facts)
    explanation = complete(prompt, SYSTEM_WHY)

    change_1d = summary.get("change_pct", 0)
    moves = multi_window.get("moves", {})
    header_pcts = f"1D {fmt_pct(change_1d)}"
    if moves.get("7d") is not None:
        header_pcts += f"  7D {fmt_pct(moves['7d'])}"
    print_header(f"WHY {symbol}?   {header_pcts}")
    print(explanation)
    print(separator("═"))


def cmd_levels(symbol: str) -> None:
    crypto_asset = is_crypto(symbol)
    print(f"\nFetching levels for {symbol}...")

    df = fetch_ohlcv(symbol, is_crypto=crypto_asset, days=210)
    if df is None:
        print(f"No price data for {symbol}.")
        return

    summary = (
        get_crypto_summary(symbol)
        if crypto_asset
        else get_price_summary(symbol, is_crypto=False)
    )
    if summary is None:
        print(f"No summary available for {symbol}.")
        return

    technicals = calculate_technicals(df)

    print_header(f"LEVELS — {symbol}")
    print(levels_table(symbol, summary, technicals))
    print(separator("═"))
