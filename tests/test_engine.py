import copy
import datetime
import json
import unittest
from unittest.mock import patch

import app
from risk import evaluate_exit, risk_state
from entry_guards import freshness


def position(side=-1, entry=0.00039):
    return {"entry":entry,"side":side,"leverage":10.0,"margin":25.0,
            "notional":250.0,"locked":False,"stop":None,"peak":entry,
            "opened":"2026-10-23T07:46:35+00:00","t":1792741595.0,
            "headline":"fixture","event_id":None,"history":[]}


class RiskTests(unittest.TestCase):
    def test_not_restart_preserves_extreme_and_exits_at_current_quote(self):
        p, why = evaluate_exit(position(),0.000380,"before-restart")
        self.assertIsNone(why)
        restored = position()
        restored.update(json.loads(json.dumps(risk_state(p))))
        restored.update(locked=p["locked"],stop=p["stop"])
        p2, why = evaluate_exit(restored,0.000388,"after-restart")
        self.assertEqual(p2["peak"],0.000380)
        self.assertEqual(p2["last_price"],0.000388)
        self.assertEqual(why,"profit_protection_stop")

    def test_saved_stop_works_without_history_or_armed_trailing(self):
        p=position();p.update(locked=True,stop=0.000387075)
        _,why=evaluate_exit(p,0.000388,"now")
        self.assertEqual(why,"profit_protection_stop")

    def test_long_and_short_trailing_never_loosen(self):
        for side,prices in [(1,[100,102,104,103.9]),(-1,[100,98,96,96.1])]:
            p=position(side,100);last=None
            for price in prices:
                p,_=evaluate_exit(p,price,"now")
                stop=p.get("trail_stop")
                if last is not None:self.assertGreaterEqual(side*(stop-last),0)
                if stop is not None:last=stop

    def test_trailing_stop_executes_without_weakening_gate(self):
        p=position(1,100)
        p,_=evaluate_exit(p,102,"peak")
        p,why=evaluate_exit(p,101.6,"retrace")
        self.assertEqual(why,"trailing_stop")

    def test_no_protection_before_profit_threshold(self):
        p,why=evaluate_exit(position(1,100),100.5,"now")
        self.assertIsNone(why);self.assertFalse(p["locked"])
        self.assertFalse(p["trail_armed"])

    def test_short_history_volatility_is_not_zeroed(self):
        p=position(1,100);p["history"]=[100,101]
        p,_=evaluate_exit(p,102,"now")
        self.assertAlmostEqual(p["last_exit_check"]["trail_gap"],0.08)

    def test_input_not_mutated(self):
        p=position();before=copy.deepcopy(p)
        evaluate_exit(p,0.00038,"now")
        self.assertEqual(p,before)

    def test_invalid_quotes_rejected(self):
        for px in [0,-1,float("nan"),float("inf")]:
            with self.assertRaises(ValueError):evaluate_exit(position(),px,"now")


class FreshnessTests(unittest.TestCase):
    def test_old_coinshares_article_is_blocked(self):
        current=datetime.datetime(2026,10,24,tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(freshness("Wed, 05 Mar 2025 08:00:00 GMT",current)["reason"],"stale_news")

    def test_exact_age_boundary(self):
        self.assertTrue(freshness("2026-10-24T00:00:00Z",1792800120)["allowed"])
        self.assertFalse(freshness("2026-10-24T00:00:00Z",1792800120.01)["allowed"])

    def test_missing_malformed_naive_or_future_publication_rejected(self):
        current=datetime.datetime(2026,10,24,tzinfo=datetime.timezone.utc).timestamp()
        for stamp in [None,"nonsense","2026-10-24T00:00:00","2026-10-25T00:00:00Z"]:
            self.assertFalse(freshness(stamp,current)["allowed"])


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy({k:v for k,v in app.S.items() if not k.startswith("_")})

    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def test_stale_event_logged_without_decision_or_entry(self):
        with patch.object(app,"save_event_feature") as feat,patch.object(app,"journal") as log,patch.object(app,"decide") as decide,patch.object(app,"open_signal") as opened:
            side=app.record_event("fixture","CoinSharesResearch","Bitcoin adoption Q4 2024","BTC",1,{"BTC":80966},"Wed, 05 Mar 2025 08:00:00 GMT")
        self.assertEqual(side,0);decide.assert_not_called();opened.assert_not_called()
        self.assertEqual(log.call_args.args[2]["reason"],"stale_news");feat.assert_called_once()

    def test_fresh_news_can_go_long_despite_bearish_structure_label(self):
        app.S["_hist"]={"BTC":[81000,80500,80000]}
        app.S["_context_cache"]={"BTC":{"epoch":app.time.time(),"context":{"market_regime":"bearish","orderbook_imbalance":-1,"funding":.005}}}
        with patch.object(app,"deep_context",side_effect=AssertionError("entry fetched network context")):
            side,_,features=app.decide("Bitcoin ETF approved","BTC",1,{"BTC":80000})
        self.assertEqual(side,1);self.assertFalse(features["market_structure_filter_active"])

    def test_explicit_notcoin_works_but_ordinary_not_does_not(self):
        prices={"NOT":.00039,"BTC":80000}
        self.assertEqual(app.detect("We are not announcing adoption",prices)[0],None)
        for text in ["$NOT partnership","NOTUSDT partnership","Notcoin partnership","NOT token partnership"]:
            self.assertEqual(app.detect(text,prices)[0],"NOT")

    def test_entry_rechecks_freshness_after_analysis(self):
        app.S.update(engine_active=True,_last_poll_epoch=app.time.time(),_prices={"BTC":80000})
        with patch.object(app,"journal"),patch.object(app.STORE,"save") as save:
            self.assertFalse(app.open_signal("BTC",1,"old",{"BTC":80000},"id","2025-03-05T08:00:00Z"))
        save.assert_not_called()

    def test_stale_market_price_blocks_fresh_news(self):
        app.S.update(engine_active=True,_last_poll_epoch=0,_prices={"BTC":80000})
        with patch.object(app,"journal") as log,patch.object(app.STORE,"save") as save:
            self.assertFalse(app.open_signal("BTC",1,"fresh",{"BTC":80000},"id",app.now()))
        self.assertEqual(log.call_args.args[2]["reason"],"stale_market_price");save.assert_not_called()

    def test_dashboard_database_reads_do_not_hold_risk_lock(self):
        def check(*args):
            self.assertFalse(app.LOCK._is_owned());return []
        with patch.object(app,"persistent_trades",side_effect=check),patch.object(app,"persistent_news",side_effect=check),patch.object(app,"persistent_features",side_effect=check):
            app.dashboard()


if __name__=="__main__":unittest.main()
