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
    get_general_market_news, get_general_crypto_news,
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

NEWS_RATE_LIMIT_NOTE = (
    "Recent news fetch was rate-limited, so this answer uses price/context data only."
)
from src.utils.formatting import (
    fmt_pct, fmt_price, print_header, print_section, separator, levels_table,
)

ROOT = pathlib.Path(__file__).parent.parent.parent
WATCHLIST_PATH = ROOT / "config" / "watchlist.yaml"

_MARKET_HIGH_RE = re.compile(
    r'\b(fed\b|federal reserve|interest rate|inflation|cpi|pce|nfp|payroll|jobs report|unemployment|gdp|treasury|yield|fomc|powell|rate hike|rate cut|rate hold)\b',
    re.IGNORECASE,
)
_MARKET_MED_RE = re.compile(
    r'\b(earnings|s&p 500|nasdaq|dow jones|semiconductor|nvidia|artificial intelligence|\btariff\b|trade war|recession|bank)\b',
    re.IGNORECASE,
)
_CRYPTO_HIGH_RE = re.compile(
    r'\b(bitcoin|btc|ethereum|eth|\bsec\b|etf|regulation|halving|liquidat|coinbase|binance|solana|stablecoin|usdt|usdc)\b',
    re.IGNORECASE,
)


def _rank_market_news(articles: list[dict], limit: int = 3) -> list[dict]:
    """Re-rank general market news: Fed/macro leads, earnings/indexes second, other last."""
    def score(a: dict) -> int:
        h = a.get("headline", "")
        if _MARKET_HIGH_RE.search(h):
            return 2
        if _MARKET_MED_RE.search(h):
            return 1
        return 0
    return sorted(articles, key=score, reverse=True)[:limit]


def _rank_crypto_news(articles: list[dict], limit: int = 3) -> list[dict]:
    """Re-rank crypto news: major coins/ETF/regulation leads."""
    def score(a: dict) -> int:
        return 1 if _CRYPTO_HIGH_RE.search(a.get("headline", "")) else 0
    return sorted(articles, key=score, reverse=True)[:limit]


def _load_watchlist() -> dict:
    with open(WATCHLIST_PATH) as f:
        return yaml.safe_load(f)


def _de_technicalize_brief(
    brief: str,
    high_impact: list[str] | None = None,
    medium_impact: list[str] | None = None,
) -> str:
    """Post-process /brief: filter TA from bullets, enforce asset format, replace UPCOMING."""
    forbidden = re.compile(
        r"\b(200-day|200D|50-day|50D|moving average|moving averages"
        r"| MA\b| MAs\b|support|resistance"
        r"|7-day high|7-day low|7D high|7D low"
        r"|20D high|20D low|20-day high|20-day low"
        r"|breakout|breakdown|watch level|key level|technical)\b",
        re.IGNORECASE,
    )
    pct_re = re.compile(r"([+-]?\d+(?:\.\d+)?%)")
    asset_re = re.compile(
        r"^([A-Z][A-Z0-9.\-]{0,9})\s+(\$[0-9][0-9,]*(?:\.[0-9]+)?[kK]?)"
        r"(?:\s*[—\-]\s*(.*))?$"
    )

    PASSTHROUGH = {"MARKET MOOD", "BIG MARKET NEWS", "BIG CRYPTO NEWS"}
    BULLET_LIMIT = {"MARKET MOOD": 2, "BIG MARKET NEWS": 3, "BIG CRYPTO NEWS": 3}
    UPCOMING_SUBS = {"HIGH IMPACT", "MEDIUM IMPACT"}
    # Varied fallback pairs — cycle per asset so identical text doesn't repeat
    _FALLBACKS = [
        ["No single direct catalyst found; move fits the broader macro/risk backdrop.", "Upcoming events, macro data, and sector or regulatory news remain the key near-term drivers."],
        ["No asset-specific catalyst identified; direction appears macro or sector-driven.", "Watch for earnings, regulatory developments, or macro data as the next catalyst."],
    ]
    _DANGLING_END_RE = re.compile(
        r'\b(as|and|but|because|since|when|while|from|for)\s*[,.]?\s*$',
        re.IGNORECASE,
    )

    def _clean_reason(text: str) -> str | None:
        """Return cleaned reason text, or None if incomplete/too short/dangling."""
        t = text.strip().rstrip(" .,")
        if not t:
            return None
        if _DANGLING_END_RE.search(t):
            return None
        if len([w for w in t.split() if len(w) > 2]) < 4:
            return None
        return t

    fallback_counter = 0

    section: str | None = None
    bullet_counts: dict[str, int] = {}
    out: list[str] = []
    lines = brief.splitlines()
    i = 0

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip().strip("*#").strip()

        if not stripped:
            i += 1
            continue

        upper = stripped.upper()

        # Top-level section header
        if upper in (PASSTHROUGH | {"WATCHLIST", "UPCOMING"}):
            if upper == "UPCOMING":
                section = "UPCOMING"
                i += 1
                continue  # skip LLM UPCOMING — we build ours at the end
            if out:
                while out and not out[-1].strip():
                    out.pop()
                out.append("")
            section = upper
            bullet_counts[upper] = 0
            out.append(upper)
            out.append("")
            i += 1
            continue

        # Sub-section headers within UPCOMING or stray WATCH NEXT — skip
        if upper in UPCOMING_SUBS or upper == "WATCH NEXT":
            i += 1
            continue

        # Skip all LLM UPCOMING body content
        if section == "UPCOMING":
            i += 1
            continue

        # Passthrough bullet sections (MARKET MOOD, BIG MARKET NEWS, BIG CRYPTO NEWS)
        if section in PASSTHROUGH:
            limit = BULLET_LIMIT.get(section, 3)
            if bullet_counts.get(section, 0) < limit and stripped.startswith(("- ", "• ", "* ", "-", "•")):
                bullet = stripped.lstrip("-•* ").strip()
                if bullet and not forbidden.search(bullet):
                    cleaned = _clean_reason(bullet)
                    if cleaned:
                        out.append(f"• {cleaned}")
                        bullet_counts[section] = bullet_counts.get(section, 0) + 1
            i += 1
            continue

        # WATCHLIST asset parser
        if section == "WATCHLIST" and (stripped.startswith("- ") or stripped.startswith("• ")):
            body = stripped.lstrip("-• ").strip()
            m = asset_re.match(body)
            if not m:
                i += 1
                continue

            sym = m.group(1)
            price = m.group(2)
            detail = (m.group(3) or "").strip()

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

            pct_match = pct_re.search(detail)
            if not pct_match:
                for sr in sub_reasons:
                    pct_match = pct_re.search(sr)
                    if pct_match:
                        break
            pct = pct_match.group(1) if pct_match else "N/A"

            if sub_reasons:
                clean = [_clean_reason(r) for r in sub_reasons if not forbidden.search(r)]
                clean = [r for r in clean if r]
            else:
                clauses = [c.strip(" .") for c in re.split(r";\s*|(?<=[.])\s+", detail) if c.strip(" .")]
                clean = [
                    _clean_reason(c) for c in clauses
                    if not forbidden.search(c)
                    and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", c)
                    and c != pct
                ]
                clean = [r for r in clean if r]

            # Deduplicate while preserving order
            seen: set[str] = set()
            deduped: list[str] = []
            for r in clean:
                if r.lower() not in seen:
                    seen.add(r.lower())
                    deduped.append(r)
            clean = deduped

            # Cycle fallback pairs so identical text never repeats across assets
            fb = _FALLBACKS[fallback_counter % len(_FALLBACKS)]
            fallback_counter += 1
            for f in fb:
                if len(clean) >= 2:
                    break
                if f not in clean:
                    clean.append(f)

            out.append(f"• {sym} {price} — {pct}")
            out.append(f"  1) {clean[0]}")
            out.append(f"  2) {clean[1]}")
            out.append("")
            i = j
            continue

        i += 1

    while out and not out[-1].strip():
        out.pop()

    # Build UPCOMING from real data (never from LLM)
    _high = high_impact or []
    _medium = medium_impact or [
        "• Fed speakers / rate expectations.",
        "• Crypto ETF flows and regulation headlines.",
    ]

    out.extend(["", "UPCOMING"])
    if _high:
        out.extend(["", "HIGH IMPACT", ""])
        out.extend(_high)
    out.extend(["", "MEDIUM IMPACT", ""])
    out.extend(_medium[:3])

    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


_CRYPTO_ALIASES: dict[str, list[str]] = {
    "BTC": ["bitcoin"],
    "ETH": ["ethereum"],
    "SOL": ["solana"],
    "XRP": ["ripple", "xrp"],
    "BNB": ["binance", "bnb"],
    "DOGE": ["dogecoin", "doge"],
    "ADA": ["cardano"],
    "AVAX": ["avalanche"],
    "MATIC": ["polygon", "matic"],
    "DOT": ["polkadot"],
    "LINK": ["chainlink"],
    "LTC": ["litecoin"],
    "ATOM": ["cosmos"],
}

_STOCK_ALIASES: dict[str, list[str]] = {
    "MSFT": ["microsoft"],
    "NVDA": ["nvidia"],
    "TSLA": ["tesla"],
    "AAPL": ["apple"],
    "GOOG": ["google", "alphabet"],
    "GOOGL": ["google", "alphabet"],
    "META": ["meta platforms", "facebook"],
    "AMZN": ["amazon"],
    "AMD": ["advanced micro"],
    "INTC": ["intel"],
    "QCOM": ["qualcomm"],
    "NFLX": ["netflix"],
    "ORCL": ["oracle"],
    "CRM": ["salesforce"],
    "VOO": ["vanguard s&p", "vanguard s&amp;p"],
    "QQQ": ["invesco", "nasdaq-100"],
    "IWM": ["russell 2000", "ishares russell"],
    "DIA": ["dow jones", "diamonds"],
    "SPY": ["s&p 500 etf", "spdr"],
}


def _is_relevant_news(headline: str, sym: str, asset_type: str) -> bool:
    """Return True if the headline is plausibly about the given symbol."""
    h = headline.lower()
    if sym.lower() in h:
        return True
    if asset_type == "crypto":
        for alias in _CRYPTO_ALIASES.get(sym, []):
            if alias in h:
                return True
    else:
        for alias in _STOCK_ALIASES.get(sym, []):
            if alias in h:
                return True
    return False


def _fill_missing_watchlist(brief: str, watchlist_facts: list[dict]) -> str:
    """Append fallback WATCHLIST entries for any symbols the LLM omitted."""
    lines = brief.splitlines()

    watchlist_start: int | None = None
    upcoming_start: int | None = None
    for idx, line in enumerate(lines):
        s = line.strip()
        if s == "WATCHLIST":
            watchlist_start = idx
        elif s == "UPCOMING" and watchlist_start is not None:
            upcoming_start = idx
            break

    if watchlist_start is None:
        return brief

    end = upcoming_start if upcoming_start is not None else len(lines)
    sym_re = re.compile(r"^[•\-]\s+([A-Z][A-Z0-9.\-]{0,9})\s+\$")
    present: set[str] = set()
    for line in lines[watchlist_start:end]:
        m = sym_re.match(line.strip())
        if m:
            present.add(m.group(1))

    missing = [f for f in watchlist_facts if f["symbol"] not in present]
    if not missing:
        return brief

    fallback_lines: list[str] = []
    for f in missing:
        sym = f["symbol"]
        price = f.get("formatted_price") or fmt_price(f.get("price"))
        pct = f.get("formatted_change_pct") or fmt_pct(f.get("change_pct", 0))
        asset_type = f.get("asset_type", "stock")
        pct_val = float(f.get("change_pct") or 0)

        moves = f.get("moves", {})
        m7d = moves.get("7d") or 0
        m30d = moves.get("30d") or 0
        news_items = f.get("news") or f.get("recent_news") or []
        all_headlines = [n.get("headline", "").strip() for n in news_items if n.get("headline")]
        relevant = [h for h in all_headlines if _is_relevant_news(h, sym, asset_type)]
        first_news = relevant[0] if relevant else ""

        if asset_type == "crypto":
            if first_news:
                short = first_news[:130].rstrip(" .,;")
                r1 = f"Recent context: {short}."
            elif m7d < -5:
                r1 = f"{sym} pulled back over the past week; macro/risk pressure and absence of a positive catalyst are the dominant drivers."
            elif m7d > 5:
                r1 = f"{sym} gained strongly over the past week; now consolidating after the recent run-up."
            elif m30d > 10:
                r1 = f"{sym} up over 30 days but facing near-term consolidation; no single catalyst found."
            else:
                r1 = f"No direct {sym} catalyst found; move reflects broader crypto/macro sentiment."
            r2 = "ETF flows, macro risk tone, and regulatory headlines remain the key crypto themes to watch."
        elif asset_type == "etf":
            if m7d < -2:
                r1 = "Tracking broader market weakness over the past week; macro and rate concerns are the dominant tone."
            elif m7d > 2:
                r1 = "Tracking broader market strength over the past week; risk-on sentiment and earnings are driving the move."
            else:
                r1 = "Little net movement over the week; reflects mixed macro/risk sentiment."
            r2 = "Fed policy, macro data releases, and earnings season are the primary near-term drivers."
        else:
            if first_news:
                short = first_news[:130].rstrip(" .,;")
                r1 = f"Recent context: {short}."
            elif m7d < -5:
                r1 = f"{sym} down over the past week; no single company-specific catalyst found."
            elif m7d > 5:
                r1 = f"{sym} strong over the past week; possible profit-taking or sector rotation after the run."
            else:
                r1 = f"No direct {sym} catalyst found; move appears tied to broader sector/macro backdrop."
            r2 = "Upcoming earnings, analyst actions, or sector data are the key near-term catalysts to watch."

        fallback_lines.append(f"• {sym} {price} — {pct}")
        fallback_lines.append(f"  1) {r1}")
        fallback_lines.append(f"  2) {r2}")
        fallback_lines.append("")

    if upcoming_start is not None:
        insert_at = upcoming_start
        while insert_at > 0 and not lines[insert_at - 1].strip():
            insert_at -= 1
        new_lines = lines[:insert_at] + [""] + fallback_lines + [""] + lines[insert_at:]
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        new_lines = lines + [""] + fallback_lines

    return "\n".join(new_lines)


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

    results: dict[str, dict] = {}
    futures = {}
    with ThreadPoolExecutor(max_workers=14) as pool:
        for sym in stocks:
            futures[pool.submit(_fetch_stock, sym, "stock")] = sym
        for sym in etfs:
            futures[pool.submit(_fetch_stock, sym, "etf")] = sym
        for sym in crypto_list:
            futures[pool.submit(_fetch_crypto, sym)] = sym

        market_news_f = pool.submit(get_general_market_news, 10)
        crypto_news_f = pool.submit(get_general_crypto_news, 10)

        for future in as_completed(futures):
            sym, data = future.result()
            if data:
                results[sym] = data

        market_news = _rank_market_news(market_news_f.result())
        crypto_news = _rank_crypto_news(crypto_news_f.result())

    fetched = len(results)
    total = len(stocks) + len(etfs) + len(crypto_list)
    print(f"Fetched {fetched}/{total} assets. Filtering movers...")

    # ETFs (always included, in watchlist order)
    etf_facts = []
    for sym in etfs:
        if sym not in results:
            continue
        d = results[sym]
        mw = d.get("multi_window", {})
        news = get_stock_news(sym, limit=3)
        etf_facts.append({
            "symbol": sym,
            "asset_type": "etf",
            "price": d["price"],
            "formatted_price": fmt_price(d["price"]),
            "change_pct": d["change_pct"],
            "formatted_change_pct": fmt_pct(d["change_pct"]),
            "moves": mw.get("moves", {}),
            "recent_news": news,
        })

    # Stock movers (top 4 by meaningfulness)
    stock_facts = []
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
            stock_facts.append(
                build_asset_facts(sym, "stock", d, tech, news, multi_window=mw, asset_class=asset_class)
            )
    stock_facts = rank_movers(stock_facts)[:4]

    # Crypto (always include all watchlist crypto)
    crypto_facts = []
    for sym in crypto_list:
        if sym not in results:
            continue
        d = results[sym]
        tech = d["technicals"]
        mw = d.get("multi_window", {})
        asset_class = classify_asset(sym, "crypto")
        news = get_crypto_news(sym, limit=3)
        crypto_facts.append(
            build_asset_facts(
                sym, "crypto", d, tech, news,
                change_7d_pct=d.get("change_7d_pct"),
                multi_window=mw,
                asset_class=asset_class,
            )
        )

    # Combined watchlist: ETFs → stocks → crypto
    watchlist_facts = etf_facts + stock_facts + crypto_facts

    # Upcoming earnings
    events = get_upcoming_earnings(stocks, days_ahead=7)

    # Build UPCOMING section content from real data
    high_impact: list[str] = []
    for ev in events[:3]:
        sym = ev.get("symbol", "")
        date_str = ev.get("date", "")
        eps = ev.get("eps_estimate")
        if sym and date_str:
            line = f"• {sym} earnings — {date_str}"
            if eps is not None:
                try:
                    line += f", EPS est. ${float(eps):.2f}"
                except (TypeError, ValueError):
                    line += f", EPS est. ${eps}"
            high_impact.append(line + ".")

    medium_impact: list[str] = [
        "• Fed speakers / rate expectations.",
        "• Crypto ETF flows and regulation headlines.",
    ]

    print("Generating brief...\n")
    prompt = build_brief_prompt(watchlist_facts, market_news, crypto_news, events)
    brief = complete(prompt, SYSTEM_BRIEF, max_tokens=1000, context="brief")
    brief = _de_technicalize_brief(brief, high_impact=high_impact, medium_impact=medium_impact)
    brief = _fill_missing_watchlist(brief, watchlist_facts)
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
    news_rate_limited = False
    if crypto_asset:
        news_by_window_raw = get_crypto_news_multi_window(symbol)
        market_context = _crypto_market_context(symbol)
    else:
        news_by_window_raw = get_stock_news_multi_window(symbol)
        market_context = _stock_market_context()
    if isinstance(news_by_window_raw, dict):
        meta = news_by_window_raw.get("_meta", {})
        if isinstance(meta, dict):
            news_rate_limited = bool(meta.get("rate_limited"))
        news_by_window = {
            "recent_1d": list(news_by_window_raw.get("recent_1d", [])),
            "recent_3d": list(news_by_window_raw.get("recent_3d", [])),
            "recent_7d": list(news_by_window_raw.get("recent_7d", [])),
            "recent_30d": list(news_by_window_raw.get("recent_30d", [])),
        }
    else:
        news_by_window = {"recent_1d": [], "recent_3d": [], "recent_7d": [], "recent_30d": []}

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
    explanation = complete(prompt, SYSTEM_WHY, context="why")
    if news_rate_limited:
        explanation = f"{explanation}\n\n{NEWS_RATE_LIMIT_NOTE}"

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
        "news_rate_limited": news_rate_limited,
        "news_warning": NEWS_RATE_LIMIT_NOTE if news_rate_limited else "",
    }


def generate_telegram_why_text(symbol: str) -> dict:
    """Like generate_why_text but includes a shorter, narrative Telegram explanation."""
    result = generate_why_text(symbol)
    facts = result.get("facts")
    if not facts:
        return result
    tg_prompt = build_telegram_why_prompt(facts)
    tg_explanation = complete(tg_prompt, SYSTEM_TELEGRAM_WHY, context="telegram_why")
    news_warning = result.get("news_warning", "")
    if news_warning:
        tg_explanation = f"{tg_explanation}\n\n{news_warning}"
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


def cmd_usage(send_telegram: bool = False) -> None:
    from src.ai.usage import load_records, build_usage_report, _sum_records
    from datetime import timezone

    records = load_records()
    if not records:
        print("\nNo usage data found. Run a command first.\n")
        return

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    today = [r for r in records if r.get("timestamp", "").startswith(today_str)]
    month = [r for r in records if r.get("timestamp", "").startswith(month_str)]

    td_calls, td_tokens, td_cost = _sum_records(today)
    mo_calls, mo_tokens, mo_cost = _sum_records(month)

    ctx_cost: dict[str, float] = {}
    for r in records:
        ctx = r.get("context") or "unknown"
        ctx_cost[ctx] = ctx_cost.get(ctx, 0.0) + (r.get("estimated_cost_usd") or 0.0)

    model_cost: dict[str, float] = {}
    for r in records:
        m = r.get("model") or "unknown"
        model_cost[m] = model_cost.get(m, 0.0) + (r.get("estimated_cost_usd") or 0.0)

    print_header("LLM USAGE")
    print(f"Today ({today_str}):")
    print(f"  Calls:          {td_calls}")
    print(f"  Tokens:         {td_tokens:,}")
    print(f"  Estimated cost: ${td_cost:.4f}")
    print()
    print(f"This month ({month_str}):")
    print(f"  Calls:          {mo_calls}")
    print(f"  Tokens:         {mo_tokens:,}")
    print(f"  Estimated cost: ${mo_cost:.4f}")
    print()
    print("By command (all time):")
    for ctx, cost in sorted(ctx_cost.items(), key=lambda x: -x[1]):
        print(f"  {ctx:<20} ${cost:.4f}")
    print()
    print("By model (all time):")
    for model, cost in sorted(model_cost.items(), key=lambda x: -x[1]):
        print(f"  {model:<30} ${cost:.4f}")
    print(separator("═"))

    if send_telegram:
        report = build_usage_report(today_str)
        send_telegram_message(report, parse_mode="HTML")
        print("Usage report sent to Telegram.")
