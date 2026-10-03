import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.config.settings import settings
from src.web.app import app
from src.web.auth import tokens_match

TOKEN = "s3cret-token"


class TokensMatchTests(unittest.TestCase):
    def test_match(self) -> None:
        self.assertTrue(tokens_match("abc", "abc"))

    def test_mismatch(self) -> None:
        self.assertFalse(tokens_match("abd", "abc"))

    def test_empty_expected_never_matches(self) -> None:
        self.assertFalse(tokens_match("", ""))
        self.assertFalse(tokens_match("abc", ""))

    def test_empty_provided_never_matches(self) -> None:
        self.assertFalse(tokens_match("", "abc"))


class AlertsScanAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._patches = [
            patch.object(settings, "ALERTS_SCAN_TOKEN", TOKEN),
            patch("src.web.app.scan_alert_events", return_value={"ok": True, "fetched": 0}),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def test_bearer_header_accepted(self) -> None:
        resp = self.client.get("/alerts/scan", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(resp.status_code, 200)

    def test_legacy_query_param_still_accepted(self) -> None:
        resp = self.client.get(f"/alerts/scan?token={TOKEN}")
        self.assertEqual(resp.status_code, 200)

    def test_wrong_bearer_rejected(self) -> None:
        resp = self.client.get("/alerts/scan", headers={"Authorization": "Bearer nope"})
        self.assertEqual(resp.status_code, 403)

    def test_wrong_query_param_rejected(self) -> None:
        resp = self.client.get("/alerts/scan?token=nope")
        self.assertEqual(resp.status_code, 403)

    def test_non_bearer_scheme_rejected(self) -> None:
        resp = self.client.get("/alerts/scan", headers={"Authorization": f"Basic {TOKEN}"})
        self.assertEqual(resp.status_code, 403)

    def test_missing_token_rejected(self) -> None:
        resp = self.client.get("/alerts/scan")
        self.assertEqual(resp.status_code, 403)

    def test_unset_server_token_rejects_everything(self) -> None:
        with patch.object(settings, "ALERTS_SCAN_TOKEN", ""):
            resp = self.client.get("/alerts/scan", headers={"Authorization": "Bearer "})
            self.assertEqual(resp.status_code, 403)
            resp = self.client.get("/alerts/scan?token=")
            self.assertEqual(resp.status_code, 403)


class UsageReportAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_wrong_token_rejected_without_sending(self) -> None:
        with (
            patch.object(settings, "USAGE_REPORT_TOKEN", TOKEN),
            patch("src.web.app.send_telegram_message") as send,
        ):
            resp = self.client.get(
                "/usage/daily-report", headers={"Authorization": "Bearer wrong"}
            )
        self.assertEqual(resp.status_code, 403)
        send.assert_not_called()

    def test_bearer_header_accepted(self) -> None:
        with (
            patch.object(settings, "USAGE_REPORT_TOKEN", TOKEN),
            patch("src.web.app.send_telegram_message") as send,
            patch("src.ai.usage.load_records", return_value=[]),
            patch("src.ai.usage.build_usage_report", return_value="report"),
        ):
            resp = self.client.get(
                "/usage/daily-report", headers={"Authorization": f"Bearer {TOKEN}"}
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
