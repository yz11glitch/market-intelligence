import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.config.settings import settings
from src.web.app import app, can_manage_chat
from src.web.auth import TELEGRAM_SECRET_HEADER

SECRET = "webhook-secret_123"
UPDATE = {"update_id": 1, "message": {"chat": {"id": 1, "type": "private"}, "text": "/help"}}


class WebhookSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        thread_patch = patch("src.web.app.threading.Thread")
        self.thread = thread_patch.start()
        self.addCleanup(thread_patch.stop)

    def test_valid_secret_accepted(self) -> None:
        with patch.object(settings, "TELEGRAM_WEBHOOK_SECRET", SECRET):
            resp = self.client.post(
                "/telegram/webhook", json=UPDATE, headers={TELEGRAM_SECRET_HEADER: SECRET}
            )
        self.assertEqual(resp.status_code, 200)
        self.thread.assert_called_once()

    def test_wrong_secret_rejected(self) -> None:
        with patch.object(settings, "TELEGRAM_WEBHOOK_SECRET", SECRET):
            resp = self.client.post(
                "/telegram/webhook", json=UPDATE, headers={TELEGRAM_SECRET_HEADER: "nope"}
            )
        self.assertEqual(resp.status_code, 403)
        self.thread.assert_not_called()

    def test_missing_secret_header_rejected(self) -> None:
        with patch.object(settings, "TELEGRAM_WEBHOOK_SECRET", SECRET):
            resp = self.client.post("/telegram/webhook", json=UPDATE)
        self.assertEqual(resp.status_code, 403)
        self.thread.assert_not_called()

    def test_not_enforced_when_secret_unset(self) -> None:
        with patch.object(settings, "TELEGRAM_WEBHOOK_SECRET", ""):
            resp = self.client.post("/telegram/webhook", json=UPDATE)
        self.assertEqual(resp.status_code, 200)
        self.thread.assert_called_once()

    def test_startup_warns_when_secret_unset(self) -> None:
        with patch.object(settings, "TELEGRAM_WEBHOOK_SECRET", ""):
            with self.assertLogs("src.web.app", level=logging.WARNING) as logs:
                with TestClient(app):
                    pass
        self.assertTrue(any("TELEGRAM_WEBHOOK_SECRET is not set" in m for m in logs.output))

    def test_startup_silent_when_secret_set(self) -> None:
        with patch.object(settings, "TELEGRAM_WEBHOOK_SECRET", SECRET):
            with self.assertNoLogs("src.web.app", level=logging.WARNING):
                with TestClient(app):
                    pass


class PrivateChatAdminTests(unittest.TestCase):
    def test_real_private_chat_can_manage(self) -> None:
        self.assertTrue(can_manage_chat(chat_id="12345", user_id="12345", chat_type="private"))

    def test_forged_private_chat_with_group_id_cannot_manage(self) -> None:
        with patch("src.web.app.get_chat_member") as get_member:
            allowed = can_manage_chat(chat_id="-1001234567890", user_id="12345", chat_type="private")
        self.assertFalse(allowed)
        get_member.assert_not_called()


if __name__ == "__main__":
    unittest.main()
