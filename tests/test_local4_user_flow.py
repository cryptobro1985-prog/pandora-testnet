import copy,datetime,os,unittest
from unittest.mock import patch
import app
from local_order_flow import dominance,pressure_exit,entry_candidate,update_watch,reentry_ready
from market_data import RollingMarketData

def flow(buy,sell,fresh=True):
    imb=(buy-sell)/(buy+sell) if buy+sell else 0.
    return dict(trade_data_fresh=fresh,latest_trade_age_seconds=1,trade_coverage_seconds=320,
                buy_volume_60s=buy,sell_volume_60s=sell,flow_imbalance=imb,
                flow_imbalance_180s=imb,flow_imbalance_300s=imb,price_return_300s=0.)

class UserFlowTests(unittest.TestCase):
    def test_current_permanent_symbols_and_requested_risk(self):
        self.assertEqual(len(app.LOCAL_EXPERIMENT_SYMBOLS),18)
        self.assertEqual(app.LOCAL_EXPERIMENT_MAX_POSITIONS,7)
        self.assertEqual(app.LOCAL_EXPERIMENT_STARTING_EQUITY,500)
        self.assertEqual(app.LOCAL_EXPERIMENT_MARGIN_FRACTION,.20)
    def test_actual_volume_majority_not_m15_scores_decides(self):
        for side in (-1,1):
            f=flow(1.001,1) if side>0 else flow(1,1.001)
            a=dict(ready=True,h1_direction_anchor=True,entry_side=side)
            self.assertTrue(entry_candidate('HYPE',a,dict(ready=False,recovery_score=0),f,100)['eligible'])
            self.assertIsNone(pressure_exit(dict(side=side,entry=100),None,99,f))
            self.assertEqual(pressure_exit(dict(side=-side,entry=100),None,99,f),'executed_flow_m1_m3_m5_opposite_control_exit')
    def test_tie_or_stale_data_never_makes_up_a_direction(self):
        self.assertEqual(dominance(flow(2,2)),0)
        self.assertIsNone(dominance(flow(3,2,False)))
        self.assertIsNone(pressure_exit(dict(side=1),None,100,flow(2,2)))
    def test_short_buying_exit_then_selling_reentry_even_above_exit(self):
        watch=dict(side=-1,exit_price=100,exit_at=100,context={})
        watch=update_watch(watch,101,None,flow(20,10),101)
        self.assertFalse(reentry_ready(-1,None,101,watch,flow(20,10),102))
        self.assertTrue(reentry_ready(-1,None,100.8,watch,flow(10,20),103))
    def test_long_selling_exit_then_buying_reentry_even_below_exit(self):
        watch=dict(side=1,exit_price=100,exit_at=100,context={})
        watch=update_watch(watch,99,None,flow(10,20),101)
        self.assertTrue(reentry_ready(1,None,99.2,watch,flow(20,10),103))
    def test_unchanged_entry_flow_cannot_manufacture_a_counter_leg(self):
        watch=update_watch(dict(side=1,exit_price=100,exit_at=100),100,None,flow(20,10),101)
        self.assertFalse(reentry_ready(1,None,100,watch,flow(20,10),102))
    def test_executed_current_bucket_counts_without_volume_baseline(self):
        obs=RollingMarketData()
        obs.mark_connected(100,{'HYPE'})
        obs.heartbeat(161)
        obs.ingest_trades([dict(coin='HYPE',side='B',px='100',sz='2',time=160500,tid=1)],161)
        result=obs.flow_context('HYPE',161)
        self.assertTrue(result['trade_data_fresh'])
        self.assertEqual(result['buy_volume_60s'],200)
        self.assertEqual(dominance(result),1)
    def test_warmup_is_data_coverage_only(self):
        obs=RollingMarketData();obs.mark_connected(100,{'HYPE'});obs.heartbeat(110)
        self.assertFalse(obs.flow_context('HYPE',110)['trade_data_fresh'])

@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class ResetTests(unittest.TestCase):
    def test_fenced_reset_is_once_only_and_preserves_nonlocal_history(self):
        from tests.test_local_candidate_storage import LocalEntryStorageTests
        fixture=LocalEntryStorageTests(methodName='test_conflicting_position_does_not_consume_signal_or_mutate_memory')
        fixture.setUp()
        try:
            with fixture.connect() as db:
                db.execute("insert into local_v12_trade_history(symbol,side,pnl,features) values('CHIP',-1,-12,'{}')")
                db.execute("insert into trade_history(symbol,pnl,strategy) values('BTC',4,'news'),('HYPE',2,'local_h1_m15_swing_v5')")
                db.execute("update local_v12_account_state set equity=10,realized_pnl=-490 where id=1")
            self.assertTrue(app.apply_local4_user_reset())
            with fixture.connect() as db:
                account=db.execute("select equity,realized_pnl from local_v12_account_state where id=1").fetchone()
                self.assertEqual((account['equity'],account['realized_pnl']),(500,0))
                self.assertEqual(db.execute("select count(*) n from local_v12_trade_history").fetchone()['n'],0)
                self.assertEqual(db.execute("select count(*) n from trade_history where strategy='news'").fetchone()['n'],1)
                self.assertEqual(db.execute("select count(*) n from trade_history where strategy like 'local%'").fetchone()['n'],0)
                db.execute("update local_v12_account_state set equity=501 where id=1")
            self.assertFalse(app.apply_local4_user_reset())
            with fixture.connect() as db:self.assertEqual(db.execute("select equity from local_v12_account_state where id=1").fetchone()['equity'],501)
        finally:fixture.tearDown()
