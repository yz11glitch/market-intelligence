import unittest
from unittest.mock import patch

from src.data import news


class _FakeStockClientSuccess:
    def company_news(self, symbol: str, _from: str, to: str) -> list[dict]:
        return [
            {
                "headline": f"{symbol} sample headline",
                "source": "Example",
                "url": "https://example.com/news",
                "datetime": 4102444800,  # 2100-01-01
            }
        ]


class _FakeStockClientRateLimited:
    def company_news(self, symbol: str, _from: str, to: str) -> list[dict]:
        raise RuntimeError("429 Too Many Requests")


class NewsResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        news._multi_window_news_cache.clear()

    def test_stock_news_uses_cache_when_rate_limited(self) -> None:
        with patch("src.data.news._finnhub_client", return_value=_FakeStockClientSuccess()):
            warm = news.get_stock_news_multi_window("NVDA")
        self.assertTrue(warm["recent_1d"])

        with patch("src.data.news._finnhub_client", return_value=_FakeStockClientRateLimited()):
            fallback = news.get_stock_news_multi_window("NVDA")

        self.assertTrue(fallback["recent_1d"])
        meta = fallback.get("_meta", {})
        self.assertTrue(meta.get("rate_limited"))
        self.assertTrue(meta.get("used_cache"))

    def test_stock_news_returns_empty_when_no_cache_and_rate_limited(self) -> None:
        with patch("src.data.news._finnhub_client", return_value=_FakeStockClientRateLimited()):
            fallback = news.get_stock_news_multi_window("AMD")

        self.assertEqual(fallback["recent_1d"], [])
        self.assertEqual(fallback["recent_3d"], [])
        self.assertEqual(fallback["recent_7d"], [])
        self.assertEqual(fallback["recent_30d"], [])
        meta = fallback.get("_meta", {})
        self.assertTrue(meta.get("rate_limited"))
        self.assertFalse(meta.get("used_cache"))


if __name__ == "__main__":
    unittest.main()
