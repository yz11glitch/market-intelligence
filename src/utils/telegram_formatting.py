import html
import re

from src.ai.client import AI_UNAVAILABLE_TEXT


SECTION_ORDER = ("MARKET MOOD", "BIG MARKET NEWS", "BIG CRYPTO NEWS", "WATCHLIST", "UPCOMING")
_WHY_HEADER_RE = re.compile(
    r"^WHY\s+(?P<symbol>[A-Za-z0-9.\-]+)\?\s+Price:\s+(?P<price>\$[0-9][0-9,]*(?:\.[0-9]+)?[kK]?)"
    r"(?:\s+1D\s+(?P<d1>[+\-]?\d+(?:\.\d+)?%|N/A))?"
    r"(?:\s+7D\s+(?P<d7>[+\-]?\d+(?:\.\d+)?%|N/A))?"
    r"(?:\s+30D\s+(?P<d30>[+\-]?\d+(?:\.\d+)?%|N/A))?",
    re.IGNORECASE,
)
_LEVELS_HEADER_RE = re.compile(
    r"^LEVELS\s+[—-]\s+(?P<symbol>[A-Za-z0-9.\-]+)\s+Price:\s+(?P<price>.+)$"
)
_TECH_HEADER_RE = re.compile(
    r"^TECH\s+(?P<symbol>[A-Za-z0-9.\-]+)\s+[—-]\s+(?P<price>.+)$"
)
_CONFIDENCE_RE = re.compile(r"\[Confidence:[^\]]+\]", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")

DISCLAIMER_HTML = "<i>Not financial advice. For information only.</i>"


_BULLET_SECTIONS = frozenset({"MARKET MOOD", "BIG MARKET NEWS", "BIG CRYPTO NEWS"})
_IMPACT_SUBSECTIONS = {"HIGH IMPACT": "🔴", "MEDIUM IMPACT": "🟠"}


def _normalize_section(line: str) -> str | None:
    normalized = line.strip().strip("*").upper()
    return normalized if normalized in SECTION_ORDER else None


def _format_asset_header(line: str) -> str:
    raw = line.lstrip("-• ").strip()
    m = re.match(
        r"^([A-Z][A-Z0-9.\-]{0,9})\s+(\$[0-9][0-9,]*(?:\.[0-9]+)?[kK]?)\s*[—-]\s*(.*)$",
        raw,
    )
    if not m:
        return f"• {html.escape(raw)}"
    sym = html.escape(m.group(1))
    price = html.escape(m.group(2))
    tail = html.escape(m.group(3))
    return f"• <b>{sym}</b> {price} — {tail}"


def _format_watch_item(line: str) -> str:
    raw = line.lstrip("-• ").strip()
    m = re.match(r"^([A-Z][A-Z0-9.\-]{0,12}\s+earnings)\b(.*)$", raw, re.IGNORECASE)
    if m:
        return f"• <b>{html.escape(m.group(1))}</b>{html.escape(m.group(2))}"
    return f"• {html.escape(raw)}"


def format_brief_for_telegram(brief_text: str, date_str: str, brief_title: str = "MARKET BRIEF") -> str:
    lines_out: list[str] = [f"📊 <b>{html.escape(brief_title)} — {html.escape(date_str)}</b>", ""]
    section: str | None = None

    for raw in brief_text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        upper = stripped.upper()

        # Top-level section headers
        if upper in frozenset(SECTION_ORDER):
            section = upper
            if lines_out and lines_out[-1]:  # blank separator before new section
                lines_out.append("")
            lines_out.append(f"<b>{stripped}</b>")
            lines_out.append("")
            continue

        # UPCOMING sub-section headers (HIGH IMPACT / MEDIUM IMPACT)
        if upper in _IMPACT_SUBSECTIONS:
            emoji = _IMPACT_SUBSECTIONS[upper]
            if lines_out and lines_out[-1]:
                lines_out.append("")
            lines_out.append(f"{emoji} <b>{stripped}</b>")
            lines_out.append("")
            continue

        if section is None:
            continue

        # MARKET MOOD, BIG MARKET NEWS, BIG CRYPTO NEWS — plain bullet lines
        if section in _BULLET_SECTIONS:
            if stripped.startswith(("•", "-")):
                text = stripped.lstrip("•- ").strip()
                lines_out.append(f"• {html.escape(text)}")
            else:
                lines_out.append(html.escape(stripped))
            continue

        # WATCHLIST — asset header format
        if section == "WATCHLIST":
            if stripped.startswith(("•", "-")):
                lines_out.append(_format_asset_header(stripped))
                continue
            if re.match(r"^[12]\)\s+", stripped):
                lines_out.append(f"  {html.escape(stripped)}")
                if stripped.startswith("2)"):
                    lines_out.append("")
                continue
            continue

        # UPCOMING — bullet lines (after HIGH IMPACT / MEDIUM IMPACT sub-headers)
        if section == "UPCOMING":
            if stripped.startswith(("•", "-")):
                text = stripped.lstrip("•- ").strip()
                lines_out.append(f"• {html.escape(text)}")
            else:
                lines_out.append(html.escape(stripped))
            continue

    while lines_out and not lines_out[-1].strip():
        lines_out.pop()
    lines_out.extend(["", DISCLAIMER_HTML])
    return "\n".join(lines_out)


def _clean_markdown_text(line: str) -> str:
    cleaned = _CONFIDENCE_RE.sub("", line)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"^[\-•]\s*", "", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


_RAW_METRICS_RE = re.compile(r"^(1D|3D|7D|30D):\s*[+\-]?\d")


def _pick_section(line: str) -> str | None:
    l = line.lower().strip()
    # Telegram-WHY simple section headers (exact match)
    if l == "story":
        return "story"
    if l == "drivers":
        return "drivers"
    if l == "technical":
        return "technical"
    if l == "watch":
        return "watch"
    if l == "sources":
        return "sources"
    # Legacy CLI-WHY section headers
    if "big picture" in l or "recent trend" in l:
        return "story"
    if "latest move" in l or "recent drivers" in l:
        return "drivers"
    if "technical context" in l:
        return "technical"
    if "watch next" in l:
        return "watch"
    if l.startswith("sources"):
        return "sources"
    return None


def _parse_source_line(line: str) -> tuple[str, str] | None:
    url_match = _URL_RE.search(line)
    if not url_match:
        return None
    url = url_match.group(0).rstrip(").,")
    title_part = line[: url_match.start()].strip(" -•:—")
    if not title_part:
        title_part = url
    return title_part, url


def _safe_bullets(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for item in items:
        cleaned = _clean_markdown_text(item)
        if not cleaned:
            continue
        if cleaned.lower().startswith("why ") and "price:" in cleaned.lower():
            continue
        if _RAW_METRICS_RE.match(cleaned):  # skip raw metric rows like "7D: -4.49% | From..."
            continue
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def format_why_for_telegram(result: dict) -> str:
    header = result.get("header", "")
    trend_line = result.get("trend_line", "")
    # Prefer the Telegram-specific narrative explanation when available
    tg_explanation = result.get("telegram_explanation", "")
    cli_explanation = result.get("explanation", "")
    explanation = tg_explanation or cli_explanation
    is_tg = bool(tg_explanation)
    explicit_warning = _clean_markdown_text(result.get("news_warning", ""))

    symbol = "?"
    price = "N/A"
    d1 = "N/A"
    d7 = "N/A"
    d30 = "N/A"
    header_match = _WHY_HEADER_RE.match(header.strip())
    if header_match:
        symbol = (header_match.group("symbol") or "?").upper()
        price = header_match.group("price") or "N/A"
        d1 = header_match.group("d1") or "N/A"
        d7 = header_match.group("d7") or "N/A"
        d30 = header_match.group("d30") or "N/A"

    sections: dict[str, list[str]] = {
        "story": [],
        "drivers": [],
        "technical": [],
        "watch": [],
    }
    warning_lines: list[str] = []
    sources: list[tuple[str, str]] = []
    current_section: str | None = None

    for raw in explanation.splitlines():
        line = _clean_markdown_text(raw)
        if not line:
            continue

        sec = _pick_section(line)
        if sec:
            current_section = sec
            continue

        if line.lower().startswith("why ") and "price:" in line.lower():
            continue

        if "rate-limit" in line.lower() or "rate limit" in line.lower() or line == AI_UNAVAILABLE_TEXT:
            warning_lines.append(line)
            continue

        if current_section == "sources":
            source = _parse_source_line(line)
            if source:
                sources.append(source)
            continue

        if current_section in sections:
            sections[current_section].append(line)

    # Only prepend trend_line when falling back to CLI explanation (Telegram output has its own story)
    if not is_tg and trend_line:
        trend_clean = _clean_markdown_text(trend_line).replace("Trend:", "").strip(" -")
        if trend_clean:
            sections["story"].insert(0, trend_clean)

    story = _safe_bullets(sections["story"], limit=2)
    drivers = _safe_bullets(sections["drivers"], limit=2)
    technical = _safe_bullets(sections["technical"], limit=2)
    watch = _safe_bullets(sections["watch"], limit=2)

    lines_out = [
        f"🧠 <b>WHY {html.escape(symbol)}?</b>",
        f"<b>Price:</b> {html.escape(price)}",
        f"<b>Move:</b> {html.escape(f'1D {d1} | 7D {d7} | 30D {d30}')}",
    ]

    if story:
        lines_out.extend(["", "<b>Story</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in story)
    warning_candidates = warning_lines.copy()
    if explicit_warning:
        warning_candidates.insert(0, explicit_warning)
    if warning_candidates:
        lines_out.extend(["", "<b>Note</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in _safe_bullets(warning_candidates, limit=1))
    if drivers:
        lines_out.extend(["", "<b>Recent drivers</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in drivers)
    if technical:
        lines_out.extend(["", "<b>Technical context</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in technical)
    if watch:
        lines_out.extend(["", "<b>Watch next</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in watch)

    if sources:
        lines_out.extend(["", "<b>Sources</b>"])
        seen: set[tuple[str, str]] = set()
        kept = 0
        for title, url in sources:
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            title_esc = html.escape(title)
            url_esc = html.escape(url, quote=True)
            lines_out.append(f'• <a href="{url_esc}">{title_esc}</a>')
            kept += 1
            if kept >= 3:
                break

    return "\n".join(lines_out)


def _extract_table_value(table_text: str, label: str) -> str | None:
    for raw in table_text.splitlines():
        line = raw.strip()
        if not line.lower().startswith(label.lower()):
            continue
        tail = line[len(label):].strip()
        if not tail:
            return None
        return re.sub(r"\s+", " ", tail)
    return None


def format_levels_for_telegram(result: dict[str, str]) -> str:
    header = result.get("header", "")
    table = result.get("table", "")
    symbol = "?"
    price = "N/A"
    m = _LEVELS_HEADER_RE.match(header.strip())
    if m:
        symbol = (m.group("symbol") or "?").upper()
        price = (m.group("price") or "N/A").strip()

    high_20d = _extract_table_value(table, "Recent High (20D)")
    low_20d = _extract_table_value(table, "Recent Low (20D)")
    ma50 = _extract_table_value(table, "50D MA")
    ma200 = _extract_table_value(table, "200D MA")
    swing_h = _extract_table_value(table, "5d Swing High")
    swing_l = _extract_table_value(table, "5d Swing Low")
    vol = _extract_table_value(table, "Volume vs 20d avg")
    change_7d = _extract_table_value(table, "7-day Change")

    lines_out = [
        f"📐 <b>LEVELS {html.escape(symbol)}</b>",
        f"<b>Price:</b> {html.escape(price)}",
    ]

    key_levels = [("20D high", high_20d), ("20D low", low_20d), ("50D MA", ma50), ("200D MA", ma200)]
    key_items = [f"{label}: {value}" for label, value in key_levels if value]
    if key_items:
        lines_out.extend(["", "<b>Key levels</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in key_items[:4])

    extra_items: list[str] = []
    if swing_h:
        extra_items.append(f"5D swing high: {swing_h}")
    if swing_l:
        extra_items.append(f"5D swing low: {swing_l}")
    if vol:
        extra_items.append(f"Volume vs 20D avg: {vol}")
    if change_7d:
        extra_items.append(f"7D change: {change_7d}")

    if extra_items:
        lines_out.extend(["", "<b>Context</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in extra_items[:4])

    return "\n".join(lines_out)


def format_tech_for_telegram(result: dict[str, str]) -> str:
    header = result.get("header", "")
    text = result.get("text", "")
    symbol = "?"
    price = "N/A"
    m = _TECH_HEADER_RE.match(header.strip())
    if m:
        symbol = (m.group("symbol") or "?").upper()
        price = (m.group("price") or "N/A").strip()

    current_section: str | None = None
    trend: list[str] = []
    levels: list[str] = []
    reads: list[str] = []
    move_line = ""

    for raw in text.splitlines():
        line = _clean_markdown_text(raw)
        if not line:
            continue
        low = line.lower()
        if low == "trend:":
            current_section = "trend"
            continue
        if low == "key levels:":
            current_section = "levels"
            continue
        if low == "read:":
            current_section = "read"
            continue

        if line.startswith("1D ") and "|" in line:
            move_line = line
            continue

        if current_section == "trend":
            trend.append(line)
        elif current_section == "levels":
            levels.append(line)
        elif current_section == "read":
            reads.append(line)

    lines_out = [
        f"📈 <b>TECH {html.escape(symbol)}</b>",
        f"<b>Price:</b> {html.escape(price)}",
    ]
    if move_line:
        lines_out.append(f"<b>Move:</b> {html.escape(move_line)}")

    trend_items = _safe_bullets(trend, limit=2)
    if trend_items:
        lines_out.extend(["", "<b>Trend</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in trend_items)

    level_items = _safe_bullets(levels, limit=5)
    if level_items:
        lines_out.extend(["", "<b>Technical context</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in level_items)

    read_items = _safe_bullets(reads, limit=3)
    if read_items:
        lines_out.extend(["", "<b>Read</b>"])
        lines_out.extend(f"• {html.escape(item)}" for item in read_items)

    return "\n".join(lines_out)
