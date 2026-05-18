import unittest
from unittest.mock import patch

from src.config.settings import settings
from src.storage.watchlists import (
    add_symbol_to_chat_watchlist,
    get_effective_watchlist,
    load_default_watchlist,
    remove_symbol_from_chat_watchlist,
)


class WatchlistFallbackTests(unittest.TestCase):
    def test_effective_watchlist_falls_back_without_database_url(self) -> None:
        with patch.object(settings, "DATABASE_URL", ""):
            watchlist, is_custom = get_effective_watchlist("12345")
        self.assertFalse(is_custom)
        self.assertEqual(watchlist, load_default_watchlist())

    def test_add_remove_are_disabled_without_database_url(self) -> None:
        with patch.object(settings, "DATABASE_URL", ""):
            add_status = add_symbol_to_chat_watchlist(chat_id="12345", symbol="btc")
            remove_status = remove_symbol_from_chat_watchlist(chat_id="12345", symbol="BTC")
        self.assertEqual(add_status, "not_enabled")
        self.assertEqual(remove_status, "not_enabled")


if __name__ == "__main__":
    unittest.main()
