import unittest

from src.bot.commands import parse_command


class ParseCommandTests(unittest.TestCase):
    def test_brief_command(self) -> None:
        parsed = parse_command("/brief")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "brief")
        self.assertIsNone(parsed.symbol)

    def test_brief_with_bot_suffix(self) -> None:
        parsed = parse_command("/brief@MarketIntelBot")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "brief")

    def test_why_command_normalizes_symbol(self) -> None:
        parsed = parse_command("/why@MarketIntelBot btc")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "why")
        self.assertEqual(parsed.symbol, "BTC")

    def test_levels_and_tech_symbol_uppercase(self) -> None:
        levels = parse_command("/levels nvda")
        tech = parse_command("/tech xrp")
        self.assertIsNotNone(levels)
        self.assertIsNotNone(tech)
        if levels is None or tech is None:
            return
        self.assertEqual(levels.symbol, "NVDA")
        self.assertEqual(tech.symbol, "XRP")

    def test_non_command_text_ignored(self) -> None:
        self.assertIsNone(parse_command("why BTC"))
        self.assertIsNone(parse_command("hello"))

    def test_missing_symbol_returns_usage_error(self) -> None:
        parsed = parse_command("/why")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.usage_error, "Use: /why BTC")

    def test_unknown_command_ignored(self) -> None:
        self.assertIsNone(parse_command("/unknown BTC"))

    def test_watchlist_show(self) -> None:
        parsed = parse_command("/watchlist show")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "watchlist")
        self.assertEqual(parsed.action, "show")
        self.assertIsNone(parsed.symbol)

    def test_watchlist_add_normalizes_symbol(self) -> None:
        parsed = parse_command("/watchlist add btc")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "watchlist")
        self.assertEqual(parsed.action, "add")
        self.assertEqual(parsed.symbol, "BTC")
        self.assertEqual(parsed.symbols, ["BTC"])

    def test_watchlist_remove(self) -> None:
        parsed = parse_command("/watchlist remove NVDA")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "watchlist")
        self.assertEqual(parsed.action, "remove")
        self.assertEqual(parsed.symbol, "NVDA")
        self.assertEqual(parsed.symbols, ["NVDA"])

    def test_watchlist_with_bot_suffix(self) -> None:
        parsed = parse_command("/watchlist@MarketIntelBot show")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "watchlist")
        self.assertEqual(parsed.action, "show")

    def test_watchlist_add_multiple_symbols_normalized_and_deduped(self) -> None:
        parsed = parse_command("/watchlist add voo qqq BTC btc  !!! eth")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "watchlist")
        self.assertEqual(parsed.action, "add")
        self.assertEqual(parsed.symbols, ["VOO", "QQQ", "BTC", "ETH"])

    def test_watchlist_remove_multiple_symbols(self) -> None:
        parsed = parse_command("/watchlist remove doge XRP sol")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "watchlist")
        self.assertEqual(parsed.action, "remove")
        self.assertEqual(parsed.symbols, ["DOGE", "XRP", "SOL"])

    def test_settings_command(self) -> None:
        parsed = parse_command("/settings")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "settings")

    def test_set_branding_command(self) -> None:
        parsed = parse_command("/set_branding Crypto Crew")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "set_branding")
        self.assertEqual(parsed.value, "Crypto Crew")

    def test_set_timezone_command(self) -> None:
        parsed = parse_command("/set_timezone Asia/Singapore")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "set_timezone")
        self.assertEqual(parsed.value, "Asia/Singapore")

    def test_set_brief_time_command(self) -> None:
        parsed = parse_command("/set_brief_time 09:00")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "set_brief_time")
        self.assertEqual(parsed.value, "09:00")

    def test_set_pin_brief_command(self) -> None:
        parsed = parse_command("/set_pin_brief on")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.command, "set_pin_brief")
        self.assertEqual(parsed.value, "on")

    def test_set_pin_brief_invalid_value(self) -> None:
        parsed = parse_command("/set_pin_brief maybe")
        self.assertIsNotNone(parsed)
        if parsed is None:
            return
        self.assertEqual(parsed.usage_error, "Use: /set_pin_brief on")


if __name__ == "__main__":
    unittest.main()
