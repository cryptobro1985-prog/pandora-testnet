import unittest
from unittest.mock import patch

import piq_direct


class PiQDirectTests(unittest.TestCase):
    def test_discover_story_links(self):
        page='''<html><body>
        <a href="/story/bitcoin-etf-flows-rise">Bitcoin ETF flows rise</a>
        <a href="https://piqmarkets.com/story/fed-cuts-rates">Fed cuts rates</a>
        </body></html>'''
        with patch("piq_direct._request", return_value=page):
            rows=piq_direct.discover(limit=10)
        urls={r["url"] for r in rows}
        self.assertIn("https://piqmarkets.com/story/bitcoin-etf-flows-rise",urls)
        self.assertIn("https://piqmarkets.com/story/fed-cuts-rates",urls)

    def test_fetch_story_uses_structured_timestamp(self):
        page='''<html><head>
        <script type="application/ld+json">
        {"@type":"NewsArticle","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30Z"}
        </script>
        </head></html>'''
        with patch("piq_direct._request", return_value=page):
            row=piq_direct.fetch_story("https://piqmarkets.com/story/test")
        self.assertEqual(row["text"],"Bitcoin ETF approved")
        self.assertEqual(row["created_at"],"2026-10-25T04:20:30+00:00")

    def test_rejects_missing_exact_timestamp(self):
        page="<html><h1>Bitcoin ETF approved</h1></html>"
        with patch("piq_direct._request", return_value=page):
            with self.assertRaises(piq_direct.PiQReadError):
                piq_direct.fetch_story("https://piqmarkets.com/story/test")

    def test_high_signal_token_boundaries(self):
        self.assertTrue(piq_direct.high_signal("ETH ETF demand rises"))
        self.assertTrue(piq_direct.high_signal("Solana upgrade goes live"))
        self.assertTrue(piq_direct.high_signal("Fed signals rate cut"))
        self.assertFalse(piq_direct.high_signal("A new enterprise solution launches"))
        self.assertFalse(piq_direct.high_signal("European property developer reports results"))


if __name__=="__main__":
    unittest.main()
