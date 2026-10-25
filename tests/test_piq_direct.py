import unittest
import json
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
        self.assertFalse(piq_direct.high_signal("Whether the cryptocurrencyologist wins a tokenization prize"))
        self.assertTrue(piq_direct.high_signal("US imposes tariffs and sanctions"))

    def story(self,page):
        with patch("piq_direct._request",return_value=page):
            return piq_direct.fetch_story("https://piqmarkets.com/story/test")

    def schema(self,value):
        return '<script type="application/ld+json">'+json.dumps(value)+'</script>'

    def test_article_headline_and_date_are_bound_to_the_same_node(self):
        page='<h1>Bitcoin ETF approved</h1>'+self.schema({"@graph":[
            {"@type":"Organization","name":"Publisher","dateCreated":"2026-10-25T09:00:00Z"},
            {"@type":"NewsArticle","url":"https://piqmarkets.com/story/related","headline":"Different story","datePublished":"2026-10-25T08:00:00Z"},
            {"@type":"NewsArticle","url":"https://piqmarkets.com/story/test","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30Z"}]})
        self.assertEqual(self.story(page)["created_at"],"2026-10-25T04:20:30+00:00")

    def test_related_article_date_cannot_supply_missing_primary_date(self):
        page='<h1>Bitcoin ETF approved</h1>'+self.schema([
            {"@type":"NewsArticle","url":"https://piqmarkets.com/story/test","headline":"Bitcoin ETF approved"},
            {"@type":"NewsArticle","url":"https://piqmarkets.com/story/related","headline":"Related","datePublished":"2026-10-25T04:20:30Z"}])
        with self.assertRaisesRegex(piq_direct.PiQReadError,"publication_timestamp_missing"):
            self.story(page)

    def test_modified_visible_and_generic_creation_times_are_not_publication(self):
        page='<h1>Bitcoin ETF approved</h1><time datetime="2026-10-25T04:20:30Z">Just now</time>'+self.schema(
            {"@type":"NewsArticle","headline":"Bitcoin ETF approved","dateCreated":"2026-10-25T04:20:30Z","dateModified":"2026-10-25T04:20:30Z"})
        with self.assertRaises(piq_direct.PiQReadError):self.story(page)
        with self.assertRaises(piq_direct.PiQReadError):
            self.story('<h1>Bitcoin ETF approved</h1><script type="application/json">{"createdAt":"2026-10-25T04:20:30Z"}</script>')

    def test_article_meta_order_and_original_time(self):
        page='<h1>Bitcoin ETF approved</h1><meta content="2026-10-25T04:20:30Z" property="article:published_time"><meta property="article:modified_time" content="2026-10-25T09:00:00Z">'
        self.assertEqual(self.story(page)["created_at"],"2026-10-25T04:20:30+00:00")

    def test_naive_publication_time_is_rejected(self):
        with self.assertRaises(piq_direct.PiQReadError):
            self.story(self.schema({"@type":"NewsArticle","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30"}))

    def test_timezone_is_normalized_to_utc(self):
        self.assertEqual(self.story(self.schema({"@type":"NewsArticle","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T08:20:30+04:00"}))["created_at"],"2026-10-25T04:20:30+00:00")

    def test_conflicting_original_timestamps_fail_closed(self):
        page=self.schema({"@type":"NewsArticle","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30Z"})+'<meta property="article:published_time" content="2026-10-25T09:00:00Z">'
        with self.assertRaisesRegex(piq_direct.PiQReadError,"conflicting_publication"):
            self.story(page)

    def test_ambiguous_article_nodes_are_rejected(self):
        page=self.schema([
            {"@type":"NewsArticle","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30Z"},
            {"@type":"NewsArticle","headline":"Bitcoin ETF rejected","datePublished":"2026-10-25T04:20:30Z"}])
        with self.assertRaisesRegex(piq_direct.PiQReadError,"ambiguous_story"):
            self.story(page)

    def test_application_data_published_at_matches_identified_story(self):
        page='<script type="application/json">'+json.dumps({"props":{"article":{"slug":"test","title":"Bitcoin ETF approved","publishedAt":"2026-10-25T04:20:30Z"}}})+'</script>'
        self.assertEqual(self.story(page)["created_at"],"2026-10-25T04:20:30+00:00")

    def test_nonarticle_schema_is_not_accepted_as_publication(self):
        with self.assertRaises(piq_direct.PiQReadError):
            self.story(self.schema({"@type":"Organization","headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30Z"}))

    def test_untrusted_or_malformed_story_urls_fail_before_network(self):
        urls=["http://piqmarkets.com/story/test","https://evil.com/story/test", "https://piqmarkets.com.evil.com/story/test", "https://u@piqmarkets.com/story/test","https://piqmarkets.com:443/story/test", "https://piqmarkets.com/story/../private","https://piqmarkets.com/story/%2e%2e", "https://piqmarkets.com/story/a%2fb"]
        for url in urls:
            with self.subTest(url=url),patch("piq_direct._request") as request:
                with self.assertRaises(piq_direct.PiQReadError):piq_direct.fetch_story(url)
                request.assert_not_called()

    def test_cached_page_for_other_story_is_rejected(self):
        with self.assertRaises(piq_direct.PiQReadError):
            self.story('<meta property="og:url" content="https://piqmarkets.com/story/other"><h1>Bitcoin ETF approved</h1><meta property="article:published_time" content="2026-10-25T04:20:30Z">')

    def test_working_ticker_does_not_fetch_duplicate_homepage(self):
        page="".join('<a href="/story/test-'+str(i)+'">Bitcoin ETF approved</a>' for i in range(10))
        with patch("piq_direct._request",return_value=page) as request:
            self.assertEqual(len(piq_direct.discover(limit=40)),10)
        request.assert_called_once()

    def test_unidentified_application_json_is_not_current_story(self):
        with self.assertRaises(piq_direct.PiQReadError):
            self.story('<script type="application/json">{"headline":"Bitcoin ETF approved","datePublished":"2026-10-25T04:20:30Z"}</script>')


if __name__=="__main__":
    unittest.main()
