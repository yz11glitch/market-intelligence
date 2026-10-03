import unittest
from unittest.mock import patch

from src.ai import client
from src.ai.client import AI_UNAVAILABLE_TEXT, complete
from src.utils.telegram_formatting import format_why_for_telegram


class AiClientErrorTests(unittest.TestCase):
    def test_provider_error_is_logged_not_returned(self) -> None:
        err = RuntimeError("Incorrect API key provided: sk-proj-****abcd")
        with (
            patch.object(client.litellm, "completion", side_effect=err),
            self.assertLogs("src.ai.client", level="WARNING") as logs,
        ):
            text = complete("prompt", "system", context="why")
        self.assertEqual(text, AI_UNAVAILABLE_TEXT)
        self.assertNotIn("AI error", text)
        self.assertNotIn("sk-proj", text)
        self.assertTrue(any("RuntimeError" in m for m in logs.output))

    def test_why_formatter_shows_neutral_note(self) -> None:
        text = format_why_for_telegram(
            {"header": "WHY BTC?   Price: $1", "telegram_explanation": AI_UNAVAILABLE_TEXT}
        )
        self.assertIn(AI_UNAVAILABLE_TEXT, text)


if __name__ == "__main__":
    unittest.main()
