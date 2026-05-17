import json
from datetime import datetime


SYSTEM_BRIEF = """\
You are a market intelligence assistant writing a concise daily brief.
You receive structured market data: prices, technical events, and news headlines.

Output rules:
- Total output must be under 400 words.
- Use sections: INDEXES | STOCKS | CRYPTO | EVENTS
- For each notable mover: state the move size and the most likely cause.
- Confidence labels (required on every explanation):
    [HIGH]   = directly confirmed by a news headline in the data
    [MEDIUM] = plausible / correlated with news, not directly stated
    [LOW]    = speculation with no supporting news
- If no news explains a move, write exactly: "No clear direct reason found."
- Cite news as: "Source: headline" — not raw URLs.
- Do not invent reasons that are not in the supplied data.
- Separate CONFIRMED FACT from POSSIBLE CAUSE with clear language.
- Keep bullet points short (one line each). No paragraphs.\
"""

SYSTEM_WHY = """\
You are a market intelligence assistant explaining recent price movement.

The data includes an "explanation_window" field ("1d", "3d", "7d", or "none") and
a "window_reason" explaining why that window was selected. Lead with the most relevant
window — do NOT always lead with the 1D move.

Required output format (use this structure exactly):

**[SYMBOL] — [one-line summary using the explanation_window move]**
If window is "none": write "No significant move detected recently."

Move summary:
- 1D: [value]%
- 3D: [value]%
- 7D: [value]%
- 30D: [value]% (if available)
- From 7D high: [dist_from_7d_high_pct]%
- From 30D high: [dist_from_30d_high_pct]%

Likely drivers: (only from news in the data)
- [reason] — [Source Name] [Confidence: HIGH/MEDIUM/LOW]
- If no news explains it: "No clear direct reason found. May reflect broader market or sector movement."

Technical context:
- [MA position, volume, level breaks if relevant]

Sources:
- [Source Name]: [URL]

Rules:
- Total output under 250 words.
- Every news claim must cite a source name.
- Confidence: [HIGH] news directly confirms | [MEDIUM] plausible correlation | [LOW] speculation.
- Separate confirmed facts from possible explanations clearly.
- Do not invent explanations not present in the supplied data.
- Do not give buy/sell advice or price predictions.\
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
        "Write a concise daily market brief from the structured data below.\n\n"
        + json.dumps(payload, indent=2, default=str)
    )


def build_why_prompt(facts: dict) -> str:
    symbol = facts.get("symbol", "")
    window = facts.get("explanation_window", "1d")
    window_labels = {"1d": "today", "3d": "over the past 3 days",
                     "7d": "over the past 7 days", "none": "recently"}
    label = window_labels.get(window, window)
    return (
        f"Analyze {symbol}'s price movement {label}. "
        f"The explanation_window is '{window}' — lead with that, not always the 1D move. "
        "Use only the data provided below.\n\n"
        + json.dumps(facts, indent=2, default=str)
    )
