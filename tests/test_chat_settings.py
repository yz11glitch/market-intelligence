import unittest
from unittest.mock import patch

from src.config.settings import settings
from src.storage.chat_settings import (
    default_chat_settings,
    get_chat_settings,
    set_chat_branding,
    set_chat_brief_time,
    set_chat_pin_daily_brief,
    set_chat_timezone,
    validate_brief_time,
    validate_timezone,
)


class ChatSettingsStorageTests(unittest.TestCase):
    def test_get_chat_settings_falls_back_without_database_url(self) -> None:
        with patch.object(settings, "DATABASE_URL", ""):
            payload = get_chat_settings("12345")
        self.assertEqual(payload, default_chat_settings())

    def test_setters_are_disabled_without_database_url(self) -> None:
        with patch.object(settings, "DATABASE_URL", ""):
            self.assertEqual(set_chat_branding("12345", "Crypto Crew"), "not_enabled")
            self.assertEqual(set_chat_timezone("12345", "Asia/Singapore"), "not_enabled")
            self.assertEqual(set_chat_brief_time("12345", "09:00"), "not_enabled")
            self.assertEqual(set_chat_pin_daily_brief("12345", True), "not_enabled")

    def test_timezone_validation(self) -> None:
        self.assertTrue(validate_timezone("Asia/Singapore"))
        self.assertFalse(validate_timezone("NotA/Zone"))

    def test_brief_time_validation(self) -> None:
        self.assertTrue(validate_brief_time("09:00"))
        self.assertFalse(validate_brief_time("24:30"))
        self.assertFalse(validate_brief_time("9:00"))


if __name__ == "__main__":
    unittest.main()
