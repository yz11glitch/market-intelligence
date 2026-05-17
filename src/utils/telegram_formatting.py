import html
import re


SECTION_ORDER = ("INDEXES", "STOCKS", "CRYPTO", "WATCH NEXT")


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


def format_brief_for_telegram(brief_text: str, date_str: str) -> str:
    lines_out: list[str] = [f"📊 <b>MARKET BRIEF — {html.escape(date_str)}</b>", ""]
    section: str | None = None

    for raw in brief_text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        sec = _normalize_section(stripped)
        if sec:
            section = sec
            lines_out.append(f"<b>{sec}</b>")
            lines_out.append("")
            continue

        if section is None:
            continue

        if section == "WATCH NEXT":
            if stripped.startswith("-") or stripped.startswith("•"):
                lines_out.append(_format_watch_item(stripped))
            else:
                lines_out.append(f"• {html.escape(stripped)}")
            continue

        if stripped.startswith("-") or stripped.startswith("•"):
            lines_out.append(_format_asset_header(stripped))
            continue

        if re.match(r"^[12]\)\s+", stripped):
            lines_out.append(f"  {html.escape(stripped)}")
            # blank line between assets for mobile readability
            if stripped.startswith("2)"):
                lines_out.append("")
            continue

        lines_out.append(html.escape(stripped))

    while lines_out and not lines_out[-1].strip():
        lines_out.pop()
    return "\n".join(lines_out)
