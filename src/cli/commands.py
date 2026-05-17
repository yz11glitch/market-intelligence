import pathlib
import re
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
    classify_move, get_pullback_from_high_context, get_recent_trend,
)
from src.analysis.facts import build_asset_facts, build_why_facts
from src.ai.client import complete
from src.ai.prompts import (
    SYSTEM_BRIEF, SYSTEM_WHY, SYSTEM_TELEGRAM_WHY,
    build_brief_prompt, build_why_prompt, build_telegram_why_prompt,
)
from src.delivery.telegram import send_telegram_message
from src.utils.telegram_formatting import format_brief_for_telegram
from src.utils.formatting import (
    fmt_pct, fmt_price, print_header, print_section, separator, levels_table,
)

ROOT = pathlib.Path(__file__).parent.parent.parent
WATCHLIST_PATH = ROOT / "config" / "watchlist.yaml"


def _load_watchlist() -> dict:
    with open(WATCHLIST_PATH) as f:
        return yaml.safe_load(f)


def _de_technicalize_brief(brief: str, watch_fallback: list[str] | None = None) -> str:
    """Post-process /brief output: filter all technical analysis from reason lines."""
    forbidden = re.compile(
        r"\b(200-day|200D|50-day|50D|moving average|moving averages"
        r"| MA\b| MAs\b|support|resistance"
        r"|7-day high|7-day low|7D high|7D low"
        r"|20D high|20D low|20-day high|20-day low"
        r"|breakout|breakdown|watch level|key level|technical)\b",
        re.IGNORECASE,
    )
    pct_re = re.compile(r"([+-]?\d+(?:\.\d+)?%)")

    defaults = {
        "INDEXES": [
            "Broad risk-off / mixed macro tone.",
            "Fed commentary is the next market focus.",
        ],
        "STOCKS": [
            "No clear direct catalyst found.",
            "Earnings and sector sentiment are in focus.",
        ],
        "CRYPTO": [
            "Little changed today; broader crypto sentiment is mixed.",
            "Context: macro pressure / ETF flows / regulation headlines.",
        ],
    }

    asset_re = re.compile(
        r"^([A-Z][A-Z0-9.\-]{0,9})\s+(\$[0-9][0-9,]*(?:\.[0-9]+)?[kK]?)"
        r"(?:\s*[—\-]\s*(.*))?$"
    )

    section: str | None = None
    out: list[str] = []
    lines = brief.splitlines()
    i = 0

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            i += 1
            continue

        if stripped in ("INDEXES", "STOCKS", "CRYPTO", "WATCH NEXT"):
            section = stripped
            out.append(stripped)
            out.append("")
            i += 1
            continue

        if section in ("INDEXES", "STOCKS", "CRYPTO") and (
            stripped.startswith("- ") or stripped.startswith("• ")
        ):
            body = stripped.lstrip("-• ").strip()
            m = asset_re.match(body)
            if not m:
                i += 1
                continue

            sym = m.group(1)
            price = m.group(2)
            detail = (m.group(3) or "").strip()

            # Collect the following 1) / 2) sub-lines (look-ahead) before touching pct
            j = i + 1
            sub_reasons: list[str] = []
            saw_sub = False
            while j < len(lines) and len(sub_reasons) < 2:
                sub = lines[j].strip()
                nm = re.match(r"^[12]\)\s+(.+)$", sub)
                if nm:
                    sub_reasons.append(nm.group(1).rstrip(" ."))
                    saw_sub = True
                    j += 1
                elif not sub:
                    j += 1
                    if saw_sub:
                        break
                else:
                    break

            # Extract pct: try header detail first, then sub-reasons
            pct_match = pct_re.search(detail)
            if not pct_match:
                for sr in sub_reasons:
                    pct_match = pct_re.search(sr)
                    if pct_match:
                        break
            pct = pct_match.group(1) if pct_match else "N/A"

            # Filter reasons — treat each sub-reason as an atomic line
            if sub_reasons:
                clean = [r for r in sub_reasons if not forbidden.search(r)]
            else:
                # Inline detail: split on semicolon/period and filter each clause
                clauses = [c.strip(" .") for c in re.split(r";\s*|(?<=[.])\s+", detail) if c.strip(" .")]
                clean = [
                    c for c in clauses
                    if not forbidden.search(c)
                    and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", c)
                    and c != pct
                ]

            for fallback in defaults.get(section, []):
                if len(clean) >= 2:
                    break
                if fallback not in clean:
                    clean.append(fallback)

            out.append(f"- {sym} {price} — {pct}")
            out.append(f"  1) {clean[0] if len(clean) > 0 else defaults[section][0]}")
            out.append(f"  2) {clean[1] if len(clean) > 1 else defaults[section][1]}")
            out.append("")
            i = j
            continue

        if section == "WATCH NEXT":
            # Skip all LLM watch items; we always build WATCH NEXT from the fallback
            i += 1
            continue

        i += 1

    # Always replace LLM WATCH NEXT with structured fallback (avoids truncation / technical leakage)
    default_watch = watch_fallback or [
        "- Fed speakers / rate expectations.",
        "- Crypto ETF flows and regulation headlines.",
    ]
    if "WATCH NEXT" in out:
        idx = out.index("WATCH NEXT")
        out = out[:idx]  # strip any partial LLM WATCH NEXT content
    out.extend(["", "WATCH NEXT", ""])
    out.extend(default_watch[:3])

    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


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

def generate_brief_text() -> tuple[str, str]:
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
                "formatted_price": fmt_price(d["price"]),
                "change_pct": d["change_pct"],
                "formatted_change_pct": fmt_pct(d["change_pct"]),
                "moves": mw.get("moves", {}),
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

    # Build watch fallback from upcoming earnings + standing items
    watch_fallback: list[str] = []
    for ev in events[:2]:
        sym = ev.get("symbol", "")
        date_str = ev.get("date", "")
        eps = ev.get("eps_estimate")
        if sym and date_str:
            line = f"- {sym} earnings — {date_str}"
            if eps is not None:
                try:
                    line += f", EPS est. ${float(eps):.2f}"
                except (TypeError, ValueError):
                    line += f", EPS est. ${eps}"
            watch_fallback.append(line + ".")
    watch_fallback += [
        "- Fed speakers / rate expectations.",
        "- Crypto ETF flows and regulation headlines.",
    ]

    print("Generating brief...\n")
    prompt = build_brief_prompt(index_facts, stock_movers, crypto_facts, events)
    brief = complete(prompt, SYSTEM_BRIEF)
    brief = _de_technicalize_brief(brief, watch_fallback=watch_fallback)
    brief_date = datetime.now().strftime("%Y-%m-%d")
    return brief_date, brief


def cmd_brief(send_telegram: bool = False) -> None:
    brief_date, brief = generate_brief_text()
    print_header(f"MARKET BRIEF — {brief_date}")
    print(brief)
    print(separator("═"))

    if send_telegram:
        try:
            telegram_text = format_brief_for_telegram(brief, brief_date)
            send_telegram_message(telegram_text, parse_mode="HTML")
            print("Telegram delivery: sent")
        except Exception as e:
            print(f"Telegram delivery failed: {e}")
            raise SystemExit(1)


def generate_why_text(symbol: str) -> dict:
    crypto_asset = is_crypto(symbol)

    if crypto_asset:
        df = fetch_ohlcv(symbol, is_crypto=True, days=210)
        summary = get_crypto_summary(symbol)
        asset_type = "crypto"
    else:
        df = fetch_ohlcv(symbol, is_crypto=False, days=210)
        summary = get_price_summary(symbol, is_crypto=False)
        asset_type = "stock"

    if df is None or summary is None:
        raise ValueError(f"No data available for {symbol}.")

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
    return {
        "trend_line": trend_line,
        "header": f"WHY {symbol}?   {header_pcts}",
        "explanation": explanation,
        "facts": facts,
    }


def generate_telegram_why_text(symbol: str) -> dict:
    """Like generate_why_text but includes a shorter, narrative Telegram explanation."""
    result = generate_why_text(symbol)
    facts = result.get("facts")
    if not facts:
        return result
    tg_prompt = build_telegram_why_prompt(facts)
    tg_explanation = complete(tg_prompt, SYSTEM_TELEGRAM_WHY)
    return {**result, "telegram_explanation": tg_explanation}


def cmd_why(symbol: str) -> None:
    print(f"\nAnalyzing {symbol}...")
    try:
        result = generate_why_text(symbol)
    except ValueError as e:
        print(str(e))
        return

    print_header(result["header"])
    print(result["explanation"])
    print(separator("═"))


def generate_levels_text(symbol: str) -> dict:
    crypto_asset = is_crypto(symbol)

    df = fetch_ohlcv(symbol, is_crypto=crypto_asset, days=210)
    if df is None:
        raise ValueError(f"No price data for {symbol}.")

    summary = (
        get_crypto_summary(symbol)
        if crypto_asset
        else get_price_summary(symbol, is_crypto=False)
    )
    if summary is None:
        raise ValueError(f"No summary available for {symbol}.")

    technicals = calculate_technicals(df)
    return {
        "header": f"LEVELS — {symbol}   Price: {fmt_price(summary.get('price'))}",
        "table": levels_table(symbol, summary, technicals),
    }


def cmd_levels(symbol: str) -> None:
    print(f"\nFetching levels for {symbol}...")
    try:
        result = generate_levels_text(symbol)
    except ValueError as e:
        print(str(e))
        return

    print_header(result["header"])
    print(result["table"])
    print(separator("═"))


def generate_tech_text(symbol: str) -> dict:
    crypto_asset = is_crypto(symbol)
    if crypto_asset:
        df = fetch_ohlcv(symbol, is_crypto=True, days=210)
        summary = get_crypto_summary(symbol)
        asset_type = "crypto"
    else:
        df = fetch_ohlcv(symbol, is_crypto=False, days=210)
        summary = get_price_summary(symbol, is_crypto=False)
        asset_type = "stock"

    if df is None or summary is None:
        raise ValueError(f"No data available for {symbol}.")

    technicals = calculate_technicals(df)
    multi_window = calculate_multi_window_moves(df)
    moves = multi_window.get("moves", {})
    recent_context = multi_window.get("recent_context", {})
    asset_class = classify_asset(symbol, asset_type)
    pullback = get_pullback_from_high_context(recent_context).get("primary_pullback", {})
    trend_line = build_trend_summary_line(symbol, moves, recent_context, asset_class).replace("Trend: ", "")

    current = summary.get("price")
    high_20d = technicals.get("high_20d")
    low_20d = technicals.get("low_20d")
    ma50 = technicals.get("ma50")
    ma200 = technicals.get("ma200")
    vol_ratio = technicals.get("volume_ratio_20d")

    read_points: list[str] = []
    if ma50 is not None and ma200 is not None and current is not None:
        if current >= ma50 and current >= ma200:
            read_points.append("Price is above both 50D and 200D MAs.")
        elif current >= ma50 and current < ma200:
            read_points.append("Price is above 50D MA but still below 200D MA.")
        elif current < ma50 and current >= ma200:
            read_points.append("Price is below 50D MA but still above 200D MA.")
        else:
            read_points.append("Price is below both 50D and 200D MAs.")
    elif ma200 is not None and current is not None:
        if current >= ma200:
            read_points.append("Price is above the 200D MA.")
        else:
            read_points.append("Price is below the 200D MA.")

    if pullback.get("label") in {"mild", "moderate", "sharp"}:
        p_label = pullback.get("label")
        p_win = str(pullback.get("window", "")).upper()
        read_points.append(f"Recent structure: {p_label} pullback from {p_win} high.")
    elif get_recent_trend(moves) in {"strong_uptrend", "strong_downtrend"}:
        direction = "uptrend" if get_recent_trend(moves) == "strong_uptrend" else "downtrend"
        read_points.append(f"Recent structure remains a strong {direction}.")

    if ma200 is not None and high_20d is not None and low_20d is not None:
        read_points.append(
            f"Key levels: upside {fmt_price(min(ma200, high_20d))}-{fmt_price(max(ma200, high_20d))}, "
            f"downside {fmt_price(low_20d)}."
        )

    lines = [
        "Trend:",
        f"- {trend_line}.",
        f"- 1D {fmt_pct(moves.get('1d'))} | 3D {fmt_pct(moves.get('3d'))} | 7D {fmt_pct(moves.get('7d'))} | 30D {fmt_pct(moves.get('30d'))}",
        "",
        "Key levels:",
        f"- 20D high: {fmt_price(high_20d) if high_20d is not None else 'N/A'}",
        f"- 20D low: {fmt_price(low_20d) if low_20d is not None else 'N/A'}",
        f"- 50D MA: {fmt_price(ma50) if ma50 is not None else 'N/A'}",
        f"- 200D MA: {fmt_price(ma200) if ma200 is not None else 'N/A'}",
    ]
    if vol_ratio is not None:
        lines.append(f"- Volume vs 20D avg: {vol_ratio:.2f}x")

    lines.extend(["", "Read:"])
    for point in read_points[:3]:
        lines.append(f"- {point}")

    return {
        "header": f"TECH {symbol} — {fmt_price(current)}",
        "text": "\n".join(lines),
    }


def cmd_tech(symbol: str) -> None:
    print(f"\nAnalyzing technicals for {symbol}...")
    try:
        result = generate_tech_text(symbol)
    except ValueError as e:
        print(str(e))
        return
    print_header(result["header"])
    print(result["text"])
    print(separator("═"))
