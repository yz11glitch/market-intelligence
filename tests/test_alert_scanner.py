import unittest
from unittest.mock import patch

from src.alerts.scanner import scan_alert_events


class _FakeConn:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class AlertScannerTests(unittest.TestCase):
    def test_scanner_counts_inserted_and_duplicates(self) -> None:
        market_news = [
            {
                "headline": "Fed rate decision and CPI inflation update",
                "source": "Reuters",
                "url": "https://example.com/m1",
            },
            {
                "headline": "Prediction: stocks may rise this week",
                "source": "Unknown",
                "url": "https://example.com/m2",
            },
        ]
        crypto_news = [
            {
                "headline": "SEC ETF approval drives BTC inflows",
                "source": "CoinDesk",
                "url": "https://example.com/c1",
            },
        ]

        with (
            patch("src.alerts.scanner.is_database_configured", return_value=True),
            patch("src.alerts.scanner.get_connection", return_value=_FakeConn()),
            patch("src.alerts.scanner.get_general_market_news", return_value=market_news),
            patch("src.alerts.scanner.get_general_crypto_news", return_value=crypto_news),
            patch("src.alerts.scanner.load_default_watchlist", return_value={"stocks": ["NVDA"], "etfs": [], "crypto": ["BTC"]}),
            patch("src.alerts.scanner._event_exists", side_effect=[False, True, False]),
            patch("src.alerts.scanner._insert_event", return_value=True),
        ):
            summary = scan_alert_events()

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["fetched"], 3)
        self.assertEqual(summary["duplicates"], 1)
        self.assertGreaterEqual(summary["inserted"], 1)
        self.assertGreaterEqual(summary["high"] + summary["medium"], 1)


if __name__ == "__main__":
    unittest.main()
