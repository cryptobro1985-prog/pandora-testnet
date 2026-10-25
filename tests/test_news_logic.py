import unittest

from news_logic import analyze_headline, is_non_market_news


PRICES = {"BTC": 100000, "ETH": 3000, "SOL": 150, "NOT": .001, "MOVE": .4,
          "PEOPLE": .02, "ETC": 25, "TRUMP": 10, "MELANIA": 1, "GAS": 4,
          "WAR": .1, "BCH": 400, "LINK": 15, "DOGE": .2, "BNB": 600}


class CausalNewsTests(unittest.TestCase):
    def test_affirmative_events_have_causal_direction(self):
        cases = (
            ("SEC approves spot Bitcoin ETF", "BTC", 1, "ETF_APPROVAL"),
            ("Spot Ethereum ETF approved", "ETH", 1, "ETF_APPROVAL"),
            ("Bitcoin ETF approval rejected by SEC", "BTC", -1, "ETF_REJECTION"),
            ("SEC rejects Bitcoin ETF despite bullish sentiment", "BTC", -1, "ETF_REJECTION"),
            ("Bitcoin ETF not approved by SEC", "BTC", -1, "ETF_REJECTION"),
            ("Ethereum hacked: funds stolen", "ETH", -1, "HACK"),
            ("Binance will delist $NOT", "NOT", -1, "DELISTING"),
            ("Binance will list NOTUSDT", "NOT", 1, "LISTING"),
            ("Notcoin partnership announced", "NOT", 1, "ADOPTION"),
            ("$MOVE buyback announced", "MOVE", 1, "BUYBACK"),
            ("$PEOPLE net outflow reported", "PEOPLE", -1, "FUND_OUTFLOW"),
            ("Bitcoin ETF net inflows reach $1bn", "BTC", 1, "FUND_INFLOW"),
            ("SEC lawsuit against Ethereum", "ETH", -1, "ENFORCEMENT"),
            ("SEC lawsuit against Ethereum dismissed", "ETH", 1, "ENFORCEMENT_RESOLVED"),
            ("SEC drops lawsuit against Ethereum", "ETH", 1, "ENFORCEMENT_RESOLVED"),
            ("Federal Reserve cuts interest rates by 25bp", "BTC", 1, "MONETARY_EASING"),
            ("Fed cuts rates by 25bp", "BTC", 1, "MONETARY_EASING"),
            ("ECB raises rates by 50bp", "BTC", -1, "MONETARY_TIGHTENING"),
            ("Federal Reserve announces quantitative easing", "BTC", 1, "MONETARY_EASING"),
            ("Fed rate hike announced by FOMC", "BTC", -1, "MONETARY_TIGHTENING"),
            ("Trump announces tariffs on China", "BTC", -1, "RISK_OFF_GEOPOLITICS"),
            ("Trump removes tariffs on China", "BTC", 1, "RISK_ON_DEESCALATION"),
            ("Sanctions lifted after peace agreement", "BTC", 1, "RISK_ON_DEESCALATION"),
            ("Missile strike reported near Hormuz", "BTC", -1, "RISK_OFF_GEOPOLITICS"),
            ("Trump announces major operations against Iran", "BTC", -1, "RISK_OFF_GEOPOLITICS"),
            ("Ceasefire agreement signed", "BTC", 1, "RISK_ON_DEESCALATION"),
            ("Ceasefire collapses after military operations resume", "BTC", -1, "CEASEFIRE_FAILED"),
            ("Bitcoin falls as SEC approves spot Bitcoin ETF", "BTC", 1, "ETF_APPROVAL"),
        )
        for title, symbol, side, event in cases:
            with self.subTest(title=title):
                result = analyze_headline(title, PRICES)
                self.assertEqual((result["symbol"], result["side"], result["event_type"]), (symbol, side, event))
                self.assertTrue(result["evidence"])

    def test_uncertain_events_do_not_open_trades(self):
        for title in (
            "Bitcoin ETF could be approved", "Bitcoin ETF may be approved",
            "Bitcoin ETF approval expected to arrive tomorrow", "Rumor: Bitcoin ETF approved",
            "Unconfirmed: Ethereum hacked", "Will SEC approve Bitcoin ETF?",
            "If SEC approves Bitcoin ETF, bulls win", "Bitcoin ETF not yet approved",
            "Bitcoin ETF has yet to be approved", "Blackrock seeks Bitcoin ETF approval",
            "Bitcoin ETF application filed", "FOMC rate cut probability rises",
            "Bitcoin ETF approved last year", "Yesterday Ethereum was hacked",
            "Recap: Bitcoin ETF approved", "Bitcoin ETF approved 3 months ago",
            "Wall Street Journal on US officials: Trump leans toward resuming major operations against Iran despite no final decision yet",
            "Bitcoin buyback proposal", "Ethereum hack not confirmed",
            "False report: Bitcoin ETF approved", "Ceasefire talks underway",
        ):
            with self.subTest(title=title):
                self.assertEqual(analyze_headline(title, PRICES)["side"], 0)

    def test_ordinary_words_and_people_are_not_coin_entities(self):
        for title in (
            "We are not announcing adoption", "People move to a new city",
            "Trump congratulates award winners", "Melania announces partnership with a museum",
            "Gas prices fall after roadworks", "War stories launch this month",
            "A second listing goes live", "Bank merger approved",
            "Federal Reserve enforcement against former Northstar, American Express and Regions employees",
            "Please accept my apologies for not realizing monopolistic exploitation of people",
        ):
            with self.subTest(title=title):
                self.assertEqual(analyze_headline(title, PRICES)["symbol"], None)
        self.assertEqual(analyze_headline("Trump announces tariffs", PRICES)["symbol"], "BTC")

    def test_explicit_token_forms_and_aliases(self):
        for title, symbol in (
            ("$NOT partnership", "NOT"), ("NOTUSDT partnership", "NOT"),
            ("Notcoin partnership", "NOT"), ("NOT token partnership", "NOT"),
            ("Movement network partnership", "MOVE"), ("ConstitutionDAO partnership", "PEOPLE"),
            ("Ethereum Classic adoption", "ETC"), ("Bitcoin Cash adoption", "BCH"),
            ("$TRUMP listing", "TRUMP"), ("TRUMPUSDT listing", "TRUMP"),
            ("$GAS listing", "GAS"), ("$WAR listing", "WAR"),
            ("Chainlink adoption", "LINK"), ("Dogecoin adoption", "DOGE"),
        ):
            with self.subTest(title=title):
                result = analyze_headline(title, PRICES)
                self.assertEqual(result["symbol"], symbol)
                self.assertEqual(result["side"], 1)

    def test_negation_and_conflicting_news(self):
        for title in (
            "Ethereum denies hack reports", "Ethereum hack report denied",
            "Ethereum: no evidence of hack", "Ethereum was not hacked",
            "Bitcoin not announcing adoption", "Bitcoin ETF approved but Ethereum hacked",
            "Bitcoin ETF approved but Bitcoin protocol hacked",
            "Bitcoin ETF inflows and outflows both jump",
            "Bitcoin partnership denied", "Bitcoin listing cancelled",
            "Trump tariffs are not being lifted", "Trump tariffs were not imposed",
            "Ceasefire not violated",
        ):
            with self.subTest(title=title):
                self.assertEqual(analyze_headline(title, PRICES)["side"], 0)
        self.assertEqual(analyze_headline("Ethereum was not hacked. Ethereum partnership announced", PRICES)["side"], 1)

    def test_inflation_compares_actual_with_expected_not_previous(self):
        for title, side in (
            ("US CPI 3.2% vs 3.0% expected", -1),
            ("US CPI 2.8% vs Exp 3.0%", 1),
            ("PCE inflation below expectations", 1),
            ("CPI above consensus", -1),
            ("US CPI 3.0% vs 3.0% expected", 0),
            ("US CPI 3.2% vs 3.0% previous", 0),
            ("Inflation rises to 3.2%", 0),
        ):
            with self.subTest(title=title):
                self.assertEqual(analyze_headline(title, PRICES)["side"], side)

    def test_mixed_assets_are_not_dict_iteration_dependent(self):
        title = "Bitcoin ETF approved but Ethereum hacked"
        forward = analyze_headline(title, PRICES)
        reverse = analyze_headline(title, dict(reversed(list(PRICES.items()))))
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["reason"], "multiple_target_assets")

    def test_promotion_regex_boundaries_work(self):
        for text in ("Bitcoin giveaway", "Ethereum prize winner", "Congrats BTC community", "BTC webinar"):
            self.assertTrue(is_non_market_news(text))
            self.assertEqual(analyze_headline(text, PRICES)["side"], 0)
        self.assertFalse(is_non_market_news("Ethereum hacked"))
        self.assertFalse(is_non_market_news("Bitcoin hackathon starts"))

    def test_only_actual_available_markets_are_returned(self):
        self.assertIsNone(analyze_headline("Ethereum ETF approved", {"BTC": 100000})["symbol"])
        self.assertEqual(analyze_headline("FOMC cuts rates", {"ETH": 3000})["symbol"], "ETH")

    def test_price_reports_remain_delegated(self):
        for title, side in (("Bitcoin surges 10%", 1), ("Ethereum plunges 5%", -1)):
            result = analyze_headline(title, PRICES)
            self.assertEqual((result["side"], result["event_type"]), (side, "PRICE_ACTION"))
            self.assertEqual(result["reason"], "delegate_to_pump_dump_scanner")

    def test_no_substring_false_directions(self):
        for title in ("Bitcoin bank expands", "Bitcoin hackathon starts", "Ethereum approved menu explained"):
            self.assertEqual(analyze_headline(title, PRICES)["side"], 0)


if __name__ == "__main__":
    unittest.main()
