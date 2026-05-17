WIDTH = 52


def fmt_price(price: float | None) -> str:
    if price is None:
        return "N/A"
    if price >= 10_000:
        return f"${price:,.0f}"
    if price >= 1_000:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:.2f}"
    return f"${price:.4f}"


def fmt_pct(pct: float | None, pad: int = 0) -> str:
    if pct is None:
        return "N/A"
    sign = "+" if pct >= 0 else ""
    s = f"{sign}{pct:.2f}%"
    return s.rjust(pad) if pad else s


def fmt_vol_ratio(ratio: float | None) -> str:
    if ratio is None:
        return "N/A"
    label = "HIGH" if ratio >= 2.0 else "elevated" if ratio >= 1.5 else "normal"
    return f"{ratio:.1f}x avg ({label})"


def separator(char: str = "─") -> str:
    return char * WIDTH


def print_header(title: str) -> None:
    print(separator("═"))
    print(title)
    print(separator("═"))


def print_section(title: str) -> None:
    print(f"\n{title}")
    print(separator())


def levels_table(symbol: str, summary: dict, technicals: dict) -> str:
    """Build a plain-text levels table without calling the LLM."""
    current = summary["price"]
    lines = [f"{symbol} — Technical Levels", separator()]

    def row(label: str, value: float | None, ref: float | None = None) -> str:
        if value is None:
            return f"  {label:<22} {'N/A':>10}"
        val_str = fmt_price(value)
        if ref is not None and ref > 0:
            diff = ((current - ref) / ref) * 100
            tag = fmt_pct(diff)
            return f"  {label:<22} {val_str:>10}   {tag}"
        return f"  {label:<22} {val_str:>10}"

    lines.append(row("Current Price", current))
    lines.append("")

    # 20-day range
    high_20d = technicals.get("high_20d")
    low_20d = technicals.get("low_20d")
    broke_high = technicals.get("broke_20d_high", False)
    broke_low = technicals.get("broke_20d_low", False)

    h_tag = "  ← NEW HIGH" if broke_high else ""
    l_tag = "  ← NEW LOW" if broke_low else ""

    if high_20d:
        diff_h = ((current - high_20d) / high_20d) * 100
        lines.append(f"  {'20d High':<22} {fmt_price(high_20d):>10}   {fmt_pct(diff_h)}{h_tag}")
    if low_20d:
        diff_l = ((current - low_20d) / low_20d) * 100
        lines.append(f"  {'20d Low':<22} {fmt_price(low_20d):>10}   {fmt_pct(diff_l)}{l_tag}")

    lines.append("")

    # Moving averages
    ma50 = technicals.get("ma50")
    ma200 = technicals.get("ma200")
    vs_50 = technicals.get("vs_ma50_pct")
    vs_200 = technicals.get("vs_ma200_pct")

    if ma50:
        tag = fmt_pct(vs_50) if vs_50 is not None else ""
        lines.append(f"  {'50-day MA':<22} {fmt_price(ma50):>10}   {tag}")
    if ma200:
        tag = fmt_pct(vs_200) if vs_200 is not None else ""
        lines.append(f"  {'200-day MA':<22} {fmt_price(ma200):>10}   {tag}")

    lines.append("")

    # 5-day swing
    swing_h = technicals.get("swing_high_5d")
    swing_l = technicals.get("swing_low_5d")
    if swing_h:
        lines.append(f"  {'5d Swing High':<22} {fmt_price(swing_h):>10}")
    if swing_l:
        lines.append(f"  {'5d Swing Low':<22} {fmt_price(swing_l):>10}")

    # Volume
    vol_ratio = technicals.get("volume_ratio_20d")
    if vol_ratio is not None:
        lines.append("")
        lines.append(f"  {'Volume vs 20d avg':<22} {fmt_vol_ratio(vol_ratio):>10}")

    # 7-day move (crypto)
    change_7d = summary.get("change_7d_pct")
    if change_7d is not None:
        lines.append("")
        lines.append(f"  {'7-day Change':<22} {fmt_pct(change_7d):>10}")

    return "\n".join(lines)
