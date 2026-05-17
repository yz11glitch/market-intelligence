import pathlib
import yaml
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.data.prices import fetch_ohlcv, get_price_summary
from src.data.crypto import is_crypto, get_crypto_summary
from src.data.news import (
    get_stock_news, get_crypto_news, get_upcoming_earnings,
    get_stock_news_multi_window, get_crypto_news_multi_window,
)
from src.analysis.technicals import calculate_technicals, calculate_multi_window_moves
from src.analysis.movers import (
    is_meaningful_mover, rank_movers,
    classify_asset, select_explanation_window, build_trend_summary_line,
    classify_move, get_pullback_from_high_context,
)
from src.analysis.facts import build_asset_facts, build_why_facts
from src.ai.client import complete
from src.ai.prompts import SYSTEM_BRIEF, SYSTEM_WHY, build_brief_prompt, build_why_prompt
from src.utils.formatting import (
    fmt_pct, fmt_price, print_header, print_section, separator, levels_table
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
    summary["multi_window"] = calculate_multi_window_moves(df)
    summary["asset_type"] = asset_type
    return symbol, summary


def _fetch_crypto(symbol: str) -> tuple[str, dict | None]:
    df = fetch_ohlcv(symbol, is_crypto=True, days=210)
    summary = get_crypto_summary(symbol)
    if df is None or summary is None:
        return symbol, None
    summary["technicals"] = calculate_technicals(df)
    summary["multi_window"] = calculate_multi_window_moves(df)
    summary["asset_type"] = "crypto"
    return symbol, summary


# ── Context helpers for /why ─────────────────────────────────────────────────

def _stock_market_context() -> dict:
    """Fetch SPY and QQQ with 1D/7D/30D moves as benchmark context for stock /why queries."""
    ctx: dict = {}
    for sym in ("SPY", "QQQ"):
        df = fetch_ohlcv(sym, is_crypto=False, days=40)
        s = get_price_summary(sym, is_crypto=False)
        if s:
            ctx[f"{sym}_1d_pct"] = s.get("change_pct")
        if df is not None:
            mw = calculate_multi_window_moves(df)
            moves = mw.get("moves", {})
            if moves.get("7d") is not None:
                ctx[f"{sym}_7d_pct"] = moves["7d"]
            if moves.get("30d") is not None:
                ctx[f"{sym}_30d_pct"] = moves["30d"]
    return ctx


def _crypto_market_context(symbol: str) -> dict:
    """Fetch BTC (and ETH for non-ETH) with 1D/7D/30D moves as benchmark context."""
    ctx: dict = {}
    benchmarks = []
    if symbol != "BTC":
        benchmarks.append("BTC")
    if symbol not in ("BTC", "ETH"):
        benchmarks.append("ETH")
    for bench in benchmarks:
        df = fetch_ohlcv(bench, is_crypto=True, days=40)
        s = get_price_summary(bench, is_crypto=True)
        if s:
            ctx[f"{bench}_1d_pct"] = s.get("change_pct")
        if df is not None:
            mw = calculate_multi_window_moves(df)
            moves = mw.get("moves", {})
            if moves.get("7d") is not None:
                ctx[f"{bench}_7d_pct"] = moves["7d"]
            if moves.get("30d") is not None:
                ctx[f"{bench}_30d_pct"] = moves["30d"]
    return ctx


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
            mw = d.get("multi_window", {})
            index_facts.append({
                "symbol": sym,
                "price": d["price"],
                "change_pct": d["change_pct"],
                "moves": mw.get("moves", {}),
                "recent_context": mw.get("recent_context", {}),
            })

    # Stock movers
    stock_movers = []
    for sym in stocks:
        if sym not in results:
            continue
        d = results[sym]
        tech = d["technicals"]
        mw = d.get("multi_window", {})
        moves = mw.get("moves", {})
        recent_context = mw.get("recent_context", {})
        asset_class = classify_asset(sym, "stock")
        vol_ratio = tech.get("volume_ratio_20d")
        meaningful_context = any(
            classify_move(moves.get(w), asset_class, w) != "noise"
            for w in ("3d", "7d", "30d")
        ) or get_pullback_from_high_context(recent_context).get("primary_pullback", {}).get("label") != "none"
        if is_meaningful_mover(d["change_pct"], vol_ratio, is_crypto=False) or meaningful_context:
            news = get_stock_news(sym, limit=3)
            stock_movers.append(
                build_asset_facts(
                    sym,
                    "stock",
                    d,
                    tech,
                    news,
                    multi_window=mw,
                    asset_class=asset_class,
                )
            )
    stock_movers = rank_movers(stock_movers)[:4]

    # Crypto (always include all watchlist crypto)
    crypto_facts = []
    for sym in crypto_list:
        if sym not in results:
            continue
        d = results[sym]
        tech = d["technicals"]
        mw = d.get("multi_window", {})
        asset_class = classify_asset(sym, "crypto")
        news = get_crypto_news(sym, limit=2)
        crypto_facts.append(
            build_asset_facts(
                sym, "crypto", d, tech, news,
                change_7d_pct=d.get("change_7d_pct"),
                multi_window=mw,
                asset_class=asset_class,
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

    asset_class = classify_asset(symbol, asset_type)
    window, window_reason = select_explanation_window(
        multi_window.get("moves", {}), asset_class
    )
    trend_line = build_trend_summary_line(
        symbol,
        multi_window.get("moves", {}),
        multi_window.get("recent_context", {}),
        asset_class,
    )
    print(f"  {trend_line}")

    # Multi-window news (one API call, three buckets)
    if crypto_asset:
        news_by_window = get_crypto_news_multi_window(symbol)
        market_context = _crypto_market_context(symbol)
    else:
        news_by_window = get_stock_news_multi_window(symbol)
        market_context = _stock_market_context()

    # Upcoming events (stocks only; 14-day lookahead)
    upcoming_events: list[dict] = []
    if not crypto_asset:
        upcoming_events = get_upcoming_earnings([symbol], days_ahead=14)

    facts = build_why_facts(
        symbol, asset_type, asset_class, summary,
        technicals, multi_window, window, window_reason,
        news_by_window, market_context, upcoming_events,
    )

    prompt = build_why_prompt(facts)
    explanation = complete(prompt, SYSTEM_WHY)

    moves = multi_window.get("moves", {})
    change_1d = summary.get("change_pct", 0)
    header_pcts = f"Price: {fmt_price(summary.get('price'))}  1D {fmt_pct(change_1d)}"
    if moves.get("7d") is not None:
        header_pcts += f"  7D {fmt_pct(moves['7d'])}"
    if moves.get("30d") is not None:
        header_pcts += f"  30D {fmt_pct(moves['30d'])}"
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

    print_header(f"LEVELS — {symbol}   Price: {fmt_price(summary.get('price'))}")
    print(levels_table(symbol, summary, technicals))
    print(separator("═"))
