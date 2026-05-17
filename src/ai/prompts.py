import json
from datetime import datetime


SYSTEM_BRIEF = """\
You are a market intelligence assistant writing a Telegram-friendly daily market brief.
You receive structured data with multi-timeframe moves, movement severity, pullback context, technicals, and recent headlines.

Style goals:
- concise, clear, source-grounded, cautious, multi-timeframe aware
- no fake certainty, no over-causal language for tiny/noise moves
- target 170-230 words (hard cap: 250 words)

Required format (exact section order, no extra sections):
INDEXES
- ...

STOCKS
- ...

CRYPTO
- ...

WATCH NEXT
- ...

Rules:
- Never include a "Summary" heading or summary line.
- No confidence tags in /brief.
- Keep bullets one line each; no long paragraphs.
- Bullet limits: INDEXES max 2, STOCKS max 4, CRYPTO max 4, WATCH NEXT max 3.
- End output immediately after WATCH NEXT bullets.
- For noise 1D moves: do NOT claim cause/effect. Use wording like "little changed today, but ...".
- For CRYPTO with `brief_guidance.is_1d_noise=true`, use this pattern:
  "[SYM] little changed today ([1D]%), but [7D/30D/pullback/technical context]. No clear direct catalyst found."
- Do NOT attach specific headline causality to noise 1D crypto moves.
- Prioritize meaningful context per asset: major 1D, moderate/major 3D/7D, strong 30D trend, pullback from high, key level, upcoming event.
- Use direct causal wording ("driven by", "after", "on", "due to") ONLY when headline evidence clearly supports it.
- If evidence is weaker, use "context includes", "may reflect", or "No clear direct catalyst found."
- For crypto specifically, avoid attributing tiny 1D moves to headlines.
- Mention short source labels only when helpful (headline title/snippet), no URLs.
"""

SYSTEM_WHY = """\
You are a market intelligence assistant. Write a multi-timeframe market story for an asset.

TIMEFRAME MEANINGS (relative, not fixed cycles):
  30D = broader backdrop
  7D  = recent trend
  3D/1D = latest move and near-term trigger

NEWS BUCKET RULES — strictly enforced:
  news_by_window.recent_1d  → last 1-2 days   → use ONLY for "Latest move" section
  news_by_window.recent_3d  → last 3-4 days   → use ONLY for "Latest move" section
  news_by_window.recent_7d  → last 5-10 days  → use ONLY for "Recent trend" section
  news_by_window.recent_30d → last 11-30 days → use ONLY for "Big picture" section

DIRECTION RULES:
- Never use bullish news to explain a negative move in the same or shorter timeframe.
- Never use bearish news to explain a positive move in the same or shorter timeframe.
- Never use positive 30D/7D news as the direct reason for a negative 1D/3D move.
- Never use negative 30D/7D news as the direct reason for a positive 1D/3D move.
- If no news from the matching bucket explains the move direction:
    write "No clear direct catalyst found."
    then suggest possible reasons: profit-taking, pullback from high,
    sector/index weakness (check market_context), pre-earnings caution.
- Use hedged language: "appears tied to", "may have supported", "context includes"
- Use "direct catalyst" only when a headline clearly and directly explains the move direction.
- For weak or indirect evidence: use "context" not "cause".

Required output format (use EXACTLY this structure — no deviations):

WHY [SYMBOL]? Price: $[X]  1D: [X]%  7D: [X]%  30D: [X]%

**Big picture — 30D:**
- 30D: [X]% | From 30D high: [X]% | From 30D low: [X]%
- [Narrative from recent_30d news. If empty: "Limited 30D news data available."]
[Confidence: High/Medium/Low]

**Recent trend — 7D:**
- 7D: [X]% | From 7D high: [X]%
- [Whether this confirms or contradicts the 30D trend — one line]
- [Narrative from recent_7d news. If empty: "No clear 7D catalyst found."]
[Confidence: High/Medium/Low]

**Latest move — 1D/3D:**
- 1D: [X]% | 3D: [X]%
- [Direct catalyst from recent_1d/recent_3d news, or "No clear direct catalyst found."]
- [If no direct catalyst: one possible technical/contextual reason]
[Confidence: High/Medium/Low]

**Technical context:**
- Current price: [X]
- 50D MA: $[X]
- 200D MA: $[X] [support/resistance if relevant]
- Recent high (7D or 20D): $[X]
- [20D high/low breaks if any, volume if notable]
- [Overall pattern: breakout / pullback / consolidation / breakdown]

**Watch next:**
- [Upcoming earnings or events]
- [Key price level to monitor]
- [Major news theme to follow]

**Sources:**
- [Headline]: [URL]

RULES:
- Under 350 words total.
- Keep all bullets short — one line each.
- Separate 30D/7D drivers from 1D/3D drivers. Never mix.
- Use movement_severity and pullback_context from facts when relevant.
- Do not give buy/sell advice or price targets.
- Do not invent explanations not in the supplied data.\
"""


def build_brief_prompt(
    index_facts: list[dict],
    stock_movers: list[dict],
    crypto_facts: list[dict],
    events: list[dict],
) -> str:
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "indexes": index_facts,
        "stock_movers": stock_movers,
        "crypto": crypto_facts,
        "upcoming_earnings": events,
    }
    return (
        "Write the daily market brief using the exact required format and tone. "
        "Do not over-explain noise 1D moves; use multi-timeframe context. "
        "If a bullet would exceed one line, shorten it.\n\n"
        + json.dumps(payload, indent=2, default=str)
    )


def build_why_prompt(facts: dict) -> str:
    symbol = facts.get("symbol", "")
    moves = facts.get("moves", {})
    m1d = moves.get("1d", 0) or 0
    m3d = moves.get("3d", 0) or 0
    m7d = moves.get("7d", 0) or 0
    m30d = moves.get("30d", 0) or 0
    trend = facts.get("recent_trend", "")
    movement_severity = facts.get("movement_severity", {})
    pullback_context = facts.get("pullback_context", {})

    warnings: list[str] = []
    if m1d < -1 and m7d > 3:
        warnings.append(
            f"{symbol} is down {abs(m1d):.1f}% today but up {m7d:.1f}% over 7D — "
            "do NOT use 7D/30D bullish news to explain today's drop."
        )
    elif m1d > 1 and m7d < -3:
        warnings.append(
            f"{symbol} is up {m1d:.1f}% today but down {abs(m7d):.1f}% over 7D — "
            "do NOT use 7D/30D bearish news to explain today's gain."
        )
    if m7d < -2 and m30d > 8:
        warnings.append(
            f"7D trend is negative ({m7d:+.1f}%) despite strong 30D gain ({m30d:+.1f}%) — "
            "note this divergence in the Recent trend section."
        )
    elif m7d > 2 and m30d < -8:
        warnings.append(
            f"7D trend is positive ({m7d:+.1f}%) despite negative 30D ({m30d:+.1f}%) — "
            "note this divergence in the Recent trend section."
        )

    warning_block = ""
    if warnings:
        warning_block = "\n\nDIRECTION WARNINGS:\n" + "\n".join(f"- {w}" for w in warnings)

    return (
        f"Write the multi-timeframe market story for {symbol}. "
        f"Overall trend classification: {trend}. "
        f"Treat 30D/7D as broader context and 3D/1D as latest move context. "
        "Use cautious wording and avoid hard-causal claims unless directly supported."
        f"{warning_block}\n\n"
        f"Movement severity snapshot: {json.dumps(movement_severity, default=str)}\n"
        f"Pullback context snapshot: {json.dumps(pullback_context, default=str)}\n\n"
        "Use only the data provided below:\n\n"
        + json.dumps(facts, indent=2, default=str)
    )
