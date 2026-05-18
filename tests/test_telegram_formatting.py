import unittest

from src.utils.telegram_formatting import (
    format_levels_for_telegram,
    format_tech_for_telegram,
    format_why_for_telegram,
)


class TelegramFormattingTests(unittest.TestCase):
    def test_why_format_is_mobile_friendly_and_single_header(self) -> None:
        result = {
            "header": "WHY BTC?   Price: $77,944  1D -0.24%  7D -5.11%  30D +1.06%",
            "trend_line": "Trend: mild pullback from recent highs",
            "explanation": """
WHY BTC? Price: $77,944  1D: -0.24%  7D: -5.11%  30D: +1.06%

**Big picture — 30D:**
- BTC is in a mild pullback from recent highs.
- 7D trend is weak, while 30D context is mostly sideways.

**Latest move — 1D/3D:**
- Weakness appears tied to rising bond yields and inflation worries.
- Reports also mention fixed-income outflows and long liquidations.

**Technical context:**
- Current price: $77,944
- 50D MA: $75,426
- 200D MA: $81,592

**Watch next:**
- Bond yields / inflation data.
- Whether BTC can reclaim the $81.5k-$82k area.

**Sources:**
- Cointelegraph — Bitcoin price dives under $79K: https://example.com/a
- CoinDesk — Bitcoin tumbles below $79,000: https://example.com/b
""",
        }
        text = format_why_for_telegram(result)
        self.assertIn("🧠 <b>WHY BTC?</b>", text)
        self.assertEqual(text.count("WHY BTC?"), 1)
        self.assertIn("<b>Story</b>", text)
        self.assertIn("<b>Recent drivers</b>", text)
        self.assertIn("<b>Technical context</b>", text)
        self.assertIn("<b>Watch next</b>", text)
        self.assertIn("<b>Sources</b>", text)
        self.assertNotIn("**", text)
        self.assertIn('<a href="https://example.com/a">', text)

    def test_why_format_shows_rate_limit_note(self) -> None:
        text = format_why_for_telegram(
            {
                "header": "WHY NVDA?   Price: $120.00  1D -1.00%  7D -2.00%  30D +3.00%",
                "explanation": "Story\n- Pullback.",
                "news_warning": "Recent news fetch was rate-limited, so this answer uses price/context data only.",
            }
        )
        self.assertIn("<b>Note</b>", text)
        self.assertIn("rate-limited", text)

    def test_levels_and_tech_formats_do_not_use_pre_blocks(self) -> None:
        levels = format_levels_for_telegram(
            {
                "header": "LEVELS — BTC   Price: $77,858",
                "table": """
BTC — Technical Levels
────────────────────────────────────────────────────
  Current Price             $77,858
  Recent High (20D)         $82,139   -5.21%
  Recent Low (20D)          $75,776   +2.75%
  50D MA                    $75,425   +3.23%
  200D MA                   $81,592   -4.58%
""",
            }
        )
        tech = format_tech_for_telegram(
            {
                "header": "TECH BTC — $77,865",
                "text": """
Trend:
- mild pullback from recent high.
- 1D -0.34% | 3D -3.93% | 7D -5.20% | 30D +0.96%

Key levels:
- 20D high: $82,139
- 20D low: $75,776
- 50D MA: $75,425
- 200D MA: $81,592

Read:
- Price is above 50D MA but still below 200D MA.
""",
            }
        )
        self.assertNotIn("<pre>", levels)
        self.assertNotIn("<pre>", tech)
        self.assertIn("<b>LEVELS BTC</b>", levels)
        self.assertIn("<b>TECH BTC</b>", tech)


if __name__ == "__main__":
    unittest.main()
