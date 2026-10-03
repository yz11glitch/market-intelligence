import unittest
from unittest.mock import patch

from src.alerts.scanner import get_saved_alert_events
from src.web.app import _format_alerts_for_telegram


class AlertsInspectionTests(unittest.TestCase):
    def test_get_saved_alerts_reports_missing_database(self) -> None:
        with patch("src.alerts.scanner.is_database_configured", return_value=False):
            payload = get_saved_alert_events()
        self.assertFalse(payload["ok"])
        self.assertIn("DATABASE_URL is missing", payload["error"])

    def test_telegram_alerts_formatter_groups_levels_and_links(self) -> None:
        text = _format_alerts_for_telegram(
            [
                {
                    "impact_level": "high",
                    "impact_score": 9,
                    "headline": "Fed shocks markets",
                    "source": "Reuters",
                    "url": "https://example.com/a",
                    "symbols": "SPY,QQQ",
                    "first_seen_at": "2026-05-19 06:00 UTC",
                    "category": "market",
                },
                {
                    "impact_level": "medium",
                    "impact_score": 6,
                    "headline": "ETF inflows rise",
                    "source": "CoinDesk",
                    "url": "",
                    "symbols": "BTC",
                    "first_seen_at": "2026-05-19 06:10 UTC",
                    "category": "crypto",
                },
            ]
        )
        self.assertIn("🔴 <b>HIGH IMPACT</b>", text)
        self.assertIn("🟠 <b>MEDIUM IMPACT</b>", text)
        self.assertIn('<a href="https://example.com/a">Fed shocks markets</a>', text)
        self.assertIn("ETF inflows rise", text)
        self.assertTrue(text.endswith("<i>Not financial advice. For information only.</i>"))

    def test_empty_alerts_message_has_no_disclaimer(self) -> None:
        self.assertEqual(_format_alerts_for_telegram([]), "No saved market alerts found.")


if __name__ == "__main__":
    unittest.main()
