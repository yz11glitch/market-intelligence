import unittest
from unittest.mock import patch

from src.bot.commands import ParsedCommand
from src.web.app import _build_watchlist_batch_summary, _process_command


class WatchlistMultiOpsTests(unittest.TestCase):
    def test_build_add_summary(self) -> None:
        text = _build_watchlist_batch_summary(
            action="add",
            added=["VOO", "QQQ", "BTC"],
            existed=["BTC"],
            removed=[],
            missing=[],
        )
        self.assertEqual(text, "Added: VOO, QQQ, BTC\nAlready existed: BTC")

    def test_build_remove_summary(self) -> None:
        text = _build_watchlist_batch_summary(
            action="remove",
            added=[],
            existed=[],
            removed=["DOGE"],
            missing=["PEPE"],
        )
        self.assertEqual(text, "Removed: DOGE\nNot found: PEPE")

    def test_process_watchlist_add_multiple_symbols(self) -> None:
        parsed = ParsedCommand(command="watchlist", action="add", symbols=["VOO", "QQQ", "BTC"])
        with (
            patch("src.web.app.is_database_configured", return_value=True),
            patch("src.web.app.can_manage_watchlist", return_value=True),
            patch("src.web.app.add_symbol_to_chat_watchlist", side_effect=["added", "exists", "added"]),
            patch("src.web.app.send_telegram_message") as send_mock,
        ):
            _process_command("1001", "group", "my-group", "2002", parsed)

        send_mock.assert_called_once_with(
            "Added: VOO, BTC\nAlready existed: QQQ",
            chat_id="1001",
        )

    def test_process_watchlist_remove_multiple_symbols(self) -> None:
        parsed = ParsedCommand(command="watchlist", action="remove", symbols=["DOGE", "XRP", "PEPE"])
        with (
            patch("src.web.app.is_database_configured", return_value=True),
            patch("src.web.app.can_manage_watchlist", return_value=True),
            patch("src.web.app.remove_symbol_from_chat_watchlist", side_effect=["removed", "removed", "missing"]),
            patch("src.web.app.send_telegram_message") as send_mock,
        ):
            _process_command("1001", "group", "my-group", "2002", parsed)

        send_mock.assert_called_once_with(
            "Removed: DOGE, XRP\nNot found: PEPE",
            chat_id="1001",
        )


if __name__ == "__main__":
    unittest.main()
