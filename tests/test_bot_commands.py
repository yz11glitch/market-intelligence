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


if __name__ == "__main__":
    unittest.main()
