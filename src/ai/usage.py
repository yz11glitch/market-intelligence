import html
import json
import pathlib
from datetime import datetime, timezone

from src.config.settings import settings

_LOG_PATH = pathlib.Path(__file__).parent.parent.parent / "data" / "usage_log.jsonl"


def _ensure_log_dir() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_call(
    context: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> None:
    _ensure_log_dir()
    total = (input_tokens or 0) + (output_tokens or 0)
    cost = (
        ((input_tokens or 0) / 1_000_000) * settings.LLM_INPUT_COST_PER_1M
        + ((output_tokens or 0) / 1_000_000) * settings.LLM_OUTPUT_COST_PER_1M
    )
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "estimated_cost_usd": round(cost, 6),
    }
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # never crash the main command due to logging failure


def load_records() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    records = []
    with open(_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _sum_records(recs: list[dict]) -> tuple[int, int, float]:
    calls = len(recs)
    tokens = sum(r.get("total_tokens") or 0 for r in recs)
    cost = sum(r.get("estimated_cost_usd") or 0.0 for r in recs)
    return calls, tokens, cost


def build_usage_report(date_str: str | None = None) -> str:
    """Build a Telegram-ready HTML usage report. Pure Python — no LLM involved."""
    now = datetime.now(timezone.utc)
    today_str = date_str or now.strftime("%Y-%m-%d")
    month_str = today_str[:7]

    records = load_records()
    today_recs = [r for r in records if r.get("timestamp", "").startswith(today_str)]
    month_recs = [r for r in records if r.get("timestamp", "").startswith(month_str)]

    td_calls, td_tokens, td_cost = _sum_records(today_recs)
    mo_calls, mo_tokens, mo_cost = _sum_records(month_recs)

    ctx_cost: dict[str, float] = {}
    for r in records:
        ctx = r.get("context") or "unknown"
        ctx_cost[ctx] = ctx_cost.get(ctx, 0.0) + (r.get("estimated_cost_usd") or 0.0)

    lines: list[str] = [
        f"📈 <b>LLM Usage — {html.escape(today_str)}</b>",
        "",
        "<b>Today:</b>",
        f"• Calls: {td_calls}  |  Tokens: {td_tokens:,}",
        f"• Cost: ${td_cost:.4f}",
        "",
        f"<b>This month ({html.escape(month_str)}):</b>",
        f"• Calls: {mo_calls}  |  Tokens: {mo_tokens:,}",
        f"• Cost: ${mo_cost:.4f}",
    ]

    if ctx_cost:
        lines += ["", "<b>By command (all time):</b>"]
        for ctx, cost in sorted(ctx_cost.items(), key=lambda x: -x[1]):
            lines.append(f"• {html.escape(ctx)}: ${cost:.4f}")

    return "\n".join(lines)
