import unittest

from src.alerts.scorer import score_news_event


class AlertScorerTests(unittest.TestCase):
    def test_high_impact_macro_headline(self) -> None:
        scored = score_news_event(
            headline="Fed rate decision and CPI inflation shock raise recession risk amid new sanctions",
            source="Reuters",
            category="market",
            watchlist_terms=[],
        )
        self.assertGreaterEqual(scored["impact_score"], 8)
        self.assertEqual(scored["impact_level"], "high")

    def test_high_impact_crypto_headline(self) -> None:
        scored = score_news_event(
            headline="SEC signals ETF approval as Bitcoin inflows surge and liquidations spike",
            source="CoinDesk",
            category="crypto",
            watchlist_terms=["BTC", "ETH"],
        )
        self.assertGreaterEqual(scored["impact_score"], 8)
        self.assertEqual(scored["impact_level"], "high")

    def test_watchlist_ticker_match(self) -> None:
        scored = score_news_event(
            headline="NVDA earnings guidance beats expectations",
            source="Example News",
            category="stock",
            watchlist_terms=["NVDA", "TSLA"],
        )
        self.assertIn("NVDA", scored["matched_symbols"])
        self.assertIn("watchlist symbol/company mention", scored["matched_reasons"])

    def test_speculative_penalty(self) -> None:
        scored = score_news_event(
            headline="Opinion: Bitcoin may recover if risk appetite improves",
            source="Random Blog",
            category="crypto",
            watchlist_terms=[],
        )
        self.assertIn("speculative wording penalty", scored["matched_reasons"])
        self.assertLess(scored["impact_score"], 6)

    def test_score_capped_at_ten(self) -> None:
        scored = score_news_event(
            headline=(
                "Fed CPI inflation jobs yields recession warning as SEC lawsuit hits exchange hack "
                "while ETF approval inflows and NVDA earnings guidance surprise"
            ),
            source="Reuters",
            category="market",
            watchlist_terms=["NVDA", "BTC"],
        )
        self.assertEqual(scored["impact_score"], 10)

    def test_low_impact_below_six(self) -> None:
        scored = score_news_event(
            headline="Prediction: stocks could move higher this week",
            source="Unknown Source",
            category="market",
            watchlist_terms=[],
        )
        self.assertLess(scored["impact_score"], 6)
        self.assertEqual(scored["impact_level"], "low")


if __name__ == "__main__":
    unittest.main()
