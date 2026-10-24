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
    def test_long_exits_only_after_local_high_and_weakening(self):
        p=position(1,100)
        # Build a favorable move and history.
        for px in [100.1,100.2,100.3,100.4,100.5,100.6,100.7,100.8]:
            p,why=evaluate_exit(p,px,"run")
            self.assertIsNone(why)
        # Peak well above arm threshold.
        p,why=evaluate_exit(p,101.0,"peak")
        self.assertIsNone(why)
        # A single retrace is not enough without weakening history.
        p,why=evaluate_exit(p,100.75,"retrace")
        self.assertIsNone(why)
        # Falling short-term structure plus giveback closes.
        p["history"]=[100.9,100.85,100.82,100.80,100.78,100.76]
        p,why=evaluate_exit(p,100.74,"weak")
        self.assertEqual(why,"local_extreme_weakening")

    def test_short_exits_only_after_local_low_and_weakening(self):
        p=position(-1,100)
        for px in [99.9,99.8,99.7,99.6,99.5,99.4,99.3,99.2]:
            p,why=evaluate_exit(p,px,"run")
            self.assertIsNone(why)
        p,why=evaluate_exit(p,99.0,"low")
        self.assertIsNone(why)
        p["history"]=[99.1,99.15,99.18,99.20,99.22,99.24]
        p,why=evaluate_exit(p,99.26,"weak")
        self.assertEqual(why,"local_extreme_weakening")

    def test_no_trailing_or_profit_stop(self):
        p=position(1,100)
        p["locked"]=True;p["stop"]=100.3;p["trail_armed"]=True;p["trail_stop"]=100.5
        p["history"]=[100.1,100.2,100.3,100.4,100.5,100.6]
        p,why=evaluate_exit(p,100.55,"now")
        self.assertIsNone(why)
        self.assertFalse(p["trail_armed"])
        self.assertIsNone(p["trail_stop"])
        self.assertIsNone(p["stop"])

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
        app.S.update(engine_active=True,_last_poll_epoch=0,_prices={"BTC":80000},last_checkpoint=app.now())
        with patch.object(app,"journal") as log,patch.object(app.STORE,"save") as save:
            self.assertFalse(app.open_signal("BTC",1,"fresh",{"BTC":80000},"id",app.now()))
        self.assertEqual(log.call_args.args[2]["reason"],"stale_market_price");save.assert_not_called()

    def test_dashboard_database_reads_do_not_hold_risk_lock(self):
        def check(*args):
            self.assertFalse(app.LOCK._is_owned());return []
        with patch.object(app,"persistent_trades",side_effect=check),patch.object(app,"persistent_news",side_effect=check),patch.object(app,"persistent_features",side_effect=check):
            app.dashboard()

    def test_connection_compatible_with_neon_transaction_pooler(self):
        with patch.dict(app.os.environ,{"DATABASE_URL":"postgresql://fixture"}),patch.object(app.psycopg,"connect") as connect:
            app.pg()
        self.assertNotIn("options",connect.call_args.kwargs)
        self.assertEqual(connect.call_args.kwargs["connect_timeout"],5)

    def test_failed_risk_checkpoint_blocks_new_entry(self):
        app.S.update(engine_active=True,_last_poll_epoch=app.time.time(),_prices={"BTC":80000},last_checkpoint=None)
        with patch.object(app,"journal") as log,patch.object(app.STORE,"save") as save:
            self.assertFalse(app.open_signal("BTC",1,"fresh",{"BTC":80000},"id",app.now()))
        self.assertEqual(log.call_args.args[2]["reason"],"risk_checkpoint_stale");save.assert_not_called()

    def test_coordinator_database_failure_is_retried(self):
        stop=unittest.mock.Mock()
        stop.is_set.side_effect=[False,True]
        with patch.object(app,"SHUTDOWN",stop),patch.object(app.STORE,"has_lease_record",side_effect=RuntimeError("temporary")):
            app.engine_coordinator()
        stop.wait.assert_called_once_with(5)


if __name__=="__main__":unittest.main()
