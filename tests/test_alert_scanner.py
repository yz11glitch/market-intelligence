import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.alerts.scanner import (
    ERROR_DB_NOT_CONFIGURED,
    ERROR_DB_UNAVAILABLE,
    ERROR_SCAN_FAILED,
    scan_alert_events,
)
from src.config.settings import settings
from src.web.app import app


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

    def test_missing_database_url_reports_config_error(self) -> None:
        with (
            patch("src.alerts.scanner.is_database_configured", return_value=False),
            patch("src.alerts.scanner.get_general_market_news") as market,
        ):
            summary = scan_alert_events()
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["error"], ERROR_DB_NOT_CONFIGURED)
        self.assertIn("DATABASE_URL", summary["detail"])
        market.assert_not_called()

    def test_connection_failure_fails_fast_without_leaking_exception_text(self) -> None:
        secret_text = 'connection to server at "db.internal.example" failed: password for user "u"'
        with (
            patch("src.alerts.scanner.is_database_configured", return_value=True),
            patch("src.alerts.scanner.get_connection", side_effect=RuntimeError(secret_text)),
            patch("src.alerts.scanner.get_general_market_news") as market,
            patch("src.alerts.scanner.get_general_crypto_news") as crypto,
            self.assertLogs("src.alerts.scanner", level="ERROR"),
        ):
            summary = scan_alert_events()
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["error"], ERROR_DB_UNAVAILABLE)
        self.assertIn("RuntimeError", summary["detail"])
        self.assertNotIn("db.internal.example", str(summary))
        market.assert_not_called()
        crypto.assert_not_called()

    def test_processing_failure_reports_scan_failed(self) -> None:
        with (
            patch("src.alerts.scanner.is_database_configured", return_value=True),
            patch("src.alerts.scanner.get_connection", return_value=_FakeConn()),
            patch(
                "src.alerts.scanner.get_general_market_news",
                return_value=[{"headline": "Fed CPI", "source": "Reuters", "url": "u"}],
            ),
            patch("src.alerts.scanner.get_general_crypto_news", return_value=[]),
            patch("src.alerts.scanner.load_default_watchlist", return_value={}),
            patch("src.alerts.scanner._event_exists", side_effect=ValueError("boom")),
            self.assertLogs("src.alerts.scanner", level="ERROR"),
        ):
            summary = scan_alert_events()
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["error"], ERROR_SCAN_FAILED)
        self.assertNotIn("boom", str(summary))


class AlertsScanEndpointStatusTests(unittest.TestCase):
    def _get(self, summary: dict):
        with (
            patch.object(settings, "ALERTS_SCAN_TOKEN", "tok"),
            patch("src.web.app.scan_alert_events", return_value=summary),
        ):
            return TestClient(app).get("/alerts/scan", headers={"Authorization": "Bearer tok"})

    def test_database_errors_map_to_503(self) -> None:
        for code in (ERROR_DB_NOT_CONFIGURED, ERROR_DB_UNAVAILABLE):
            resp = self._get({"ok": False, "error": code, "detail": "x"})
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["error"], code)

    def test_other_failures_map_to_500(self) -> None:
        resp = self._get({"ok": False, "error": ERROR_SCAN_FAILED, "detail": "x"})
        self.assertEqual(resp.status_code, 500)

    def test_success_is_200(self) -> None:
        resp = self._get({"ok": True, "fetched": 3})
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
