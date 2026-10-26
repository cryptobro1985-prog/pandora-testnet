"""Regressions for the causal entry, common budget and emergency release."""
import copy
import unittest
import app
from emergency_guard import reversal, profit_targets
from hype_h1_swing import analyze, position_exit
from liquidation_stream import LiquidationTape, cascade_candidates
from momentum_scanner import breadth_regime, continuation_candidates, direction_guard
from whale_v2 import EligibilityTracker, initial_position_state


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        app.S.update(engine_active=True,mode="PAPER_ONLY",orders_enabled=False,equity=100.,
                     positions={},pump_positions={},whale_positions={},whale_v2_positions={},
                     hype_swing_position=None,_entry_reservations={},_emergency_until=0)

    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def market(self,side=-1):
        epoch=2000.;names=["BTC","ETH","SOL","AAA","BBB","CCC"]
        prices={s:100. for s in names};volumes={s:10e6 for s in names}
        history={s:[(epoch-age,100/(1+side*age*.00003)) for age in range(1802,0,-2)] for s in names}
        contexts={s:{"epoch":epoch,"trade_data_fresh":True,"flow_imbalance":side*.5,
                     "volume_burst_ratio":1.5,"volume_rate_z":1.2} for s in names}
        return prices,history,volumes,epoch,contexts

    def test_continuing_dump_without_new_acceleration_reaches_entry_candidates(self):
        p,h,v,t,c=self.market();r=breadth_regime(p,h,v,t)
        self.assertEqual(r["side"],-1)
        found=continuation_candidates(p,h,v,t,c,r)
        self.assertEqual(len(found),6);self.assertTrue(all(x["side"]==-1 for x in found))

    def test_countermarket_long_and_reversed_queued_long_are_rejected(self):
        p,h,v,t,c=self.market();r=breadth_regime(p,h,v,t)
        self.assertEqual(direction_guard("BTC",1,p,h,t,r),"opposite_broad_market_direction")
        self.assertEqual(direction_guard("BTC",1,p,h,t,{"side":0}),"symbol_momentum_reversed")

    def test_quiet_or_unobserved_drift_is_not_a_dump_entry(self):
        p,h,v,t,c=self.market();r=breadth_regime(p,h,v,t)
        for x in c.values():x.update(volume_burst_ratio=.8,volume_rate_z=0)
        self.assertEqual(continuation_candidates(p,h,v,t,c,r),[])
        for x in c.values():x.update(trade_data_fresh=False,volume_burst_ratio=4)
        self.assertEqual(continuation_candidates(p,h,v,t,c,r),[])

    def test_news_sources_share_real_publication_age_limit(self):
        for source in ("XOfficial:FirstSquawk","PiQDirect","CoinDesk"):
            self.assertEqual(app.source_freshness_window(source),app.NEWS_MAX_AGE_SECONDS)

    def test_all_blocks_share_budget_and_ten_percent_compounds(self):
        app.S["whale_v2_positions"]={"XXX":{"margin":30,"notional":750,"leverage":25}}
        app.S["hype_swing_position"]={"margin":20,"notional":500,"leverage":25}
        self.assertEqual(app._shared_used_margin(),50)
        self.assertEqual(app._reserve_shared_entry("NEW",strategy="whale_v2")[1],10)
        app._release_shared_entry("NEW",strategy="whale_v2");app.S["equity"]=150
        self.assertEqual(app._reserve_shared_entry("NEW",strategy="hype_swing")[1],15)

    def test_other_blocks_cannot_spend_reserved_margin(self):
        app.S["whale_v2_positions"]={"XXX":{"margin":95,"notional":2375,"leverage":25}}
        self.assertEqual(app._reserve_shared_entry("NEW")[2],"insufficient_free_margin")

    def test_emergency_cooldown_blocks_all_entry_paths(self):
        app.S.update(_emergency_until=app.time.time()+60,_prices={"BTC":100},_last_poll_epoch=app.time.time(),last_checkpoint=app.now())
        self.assertIsNone(app.current_entry_price("BTC"))
        self.assertEqual(app._reserve_shared_entry("BTC",strategy="whale_v2")[2],"emergency_profit_cooldown")

    def test_major_reversal_targets_profits_across_blocks(self):
        prices={s:100 for s in ("BTC","ETH","SOL")};history={s:[(990,100.2),(970,100.4)] for s in prices}
        shock=reversal(prices,history,1000);self.assertEqual(shock["side"],-1)
        pos={"entry":99,"side":1,"notional":250,"opened":"a"}
        targets=profit_targets([("news",{"BTC":pos}),("wl2",{"ETH":pos}),("pump",{"SOL":{**pos,"entry":101}})],prices,shock,app.FEE)
        self.assertEqual({x["strategy"] for x in targets},{"news","wl2"})

    def test_favorable_market_move_does_not_close_profitable_shorts(self):
        prices={s:100 for s in ("BTC","ETH","SOL")};history={s:[(990,100.3)] for s in prices}
        pos={"entry":101,"side":-1,"notional":250,"opened":"a"}
        self.assertEqual(profit_targets([("pump",{"BTC":pos})],prices,reversal(prices,history,1000),app.FEE),[])
        self.assertFalse(reversal({"BTC":100},{"BTC":[(999,102)]},1000)["triggered"])


class H1Tests(unittest.TestCase):
    H=3_600_000
    def rows(self,side=1):
        prices=[(100,102,95,99),(99,101,94,98),(98,100,93,97),(97,99,92,96),(96,98,85,89),(89,96,87,95)]
        rows=[]
        for i,(o,h,l,c) in enumerate(prices):
            if side<0:o,h,l,c=200-o,200-l,200-h,200-c
            rows.append(dict(t=i*self.H,T=(i+1)*self.H-1,o=o,h=h,l=l,c=c,v=1))
        return rows

    def test_confirmed_local_low_and_high_give_symmetric_entries(self):
        for side in (1,-1):
            result=analyze(self.rows(side),6*self.H+2000)
            self.assertTrue(result["ready"]);self.assertEqual(result["entry_side"],side)

    def test_unclosed_bar_cannot_create_a_future_pivot(self):
        rows=self.rows();expected=analyze(rows,6*self.H+2000)
        rows.append(dict(t=6*self.H,T=7*self.H-1,o=95,h=150,l=1,c=149,v=10000))
        self.assertEqual(analyze(rows,6*self.H+2000),expected)

    def test_malformed_and_stale_hourly_bars_cannot_authorize_entry(self):
        rows=self.rows();rows[-1]["h"]=1
        self.assertFalse(analyze(rows,6*self.H+2000)["ready"])
        self.assertEqual(analyze(self.rows(),9*self.H)["reason"],"stale_h1_history")

    def test_entry_candle_is_not_reused_as_exit(self):
        a=analyze(self.rows(),6*self.H+2000);a["long_weakening"]=True
        p={"side":1,"entry":90,"signal_candle_time":a["signal_candle_time"],"features":{"mfe_price_move":.1}}
        self.assertIsNone(position_exit(p,a,95))
        a["signal_candle_time"]+=self.H
        self.assertEqual(position_exit(p,a,95),"h1_momentum_weakening")


class CascadeTests(unittest.TestCase):
    def message(self,stamp=1000,side="SELL"):
        return {"e":"forceOrder","E":int(stamp*1000),"o":{"s":"BTCUSDT","S":side,"T":int(stamp*1000),
                "ap":"100000","l":"10","z":"10","q":"9999999","X":"FILLED"}}

    def test_side_filled_quantity_and_deduplication(self):
        tape=LiquidationTape();tape.reset(True)
        self.assertEqual(tape.ingest(self.message(),1001),1);self.assertEqual(tape.ingest(self.message(),1001),0)
        event=tape.snapshot(1001)[0]
        self.assertEqual(event["side"],-1);self.assertEqual(event["notional_usd"],1_000_000)

    def test_old_liquidations_and_coin_margined_contracts_are_rejected(self):
        tape=LiquidationTape();tape.reset(True);self.assertEqual(tape.ingest(self.message(900),1001),0)
        message=self.message();message["o"]["st"]=2
        self.assertEqual(tape.ingest(message,1001),0)

    def test_cascade_requires_local_pressure_and_starts_post_liquidation_exit(self):
        tape=LiquidationTape();tape.reset(True);tape.ingest(self.message(998),999);tape.ingest(self.message(999),1000)
        prices={"BTC":100};history={"BTC":[(985,100.1),(940,100.2)]}
        ctx={"BTC":{"epoch":1000,"trade_data_fresh":True,"flow_imbalance":-.4,"volume_burst_ratio":2}}
        books={"BTC":{"epoch":1000,"bid_depth_complete":True,"ask_depth_complete":True,"spread_bps":1,"imbalance":-.2}}
        found,_=cascade_candidates(tape.snapshot(1000),prices,history,ctx,books,1000,{"side":-1})
        self.assertEqual(len(found),1);self.assertEqual(found[0]["side"],-1)
        self.assertEqual(initial_position_state(found[0],100,"opened")["wl2_liquidation_level_reached_at"],"opened")
        ctx["BTC"]["flow_imbalance"]=.4
        self.assertEqual(cascade_candidates(tape.snapshot(1000),prices,history,ctx,books,1000,{"side":-1})[0],[])


class WL2ObservationTests(unittest.TestCase):
    def candidate(self,distance):
        return dict(symbol="AAA",side=-1,cluster_id="a",distance_pct=distance,score=95,whale_rank_score=92,
                    r15=-.001,r60=-.002,flow_imbalance=-.4,cvd_1m=-100,orderbook_imbalance=-.2,
                    spread_bps=2,micro_confirmations=4,volume_burst_ratio=3,dynamic_entry_distance_pct=1)

    def test_rejected_passes_still_build_distance_observations(self):
        tracker=EligibilityTracker()
        for scan,d in ((1,.8),(2,.77)):
            row=self.candidate(d);row["upstream_reject_reasons"]=["missing_orderbook"]
            self.assertEqual(tracker.observe([row],scan)[0],[])
        self.assertEqual(len(tracker.observe([self.candidate(.73)],3)[0]),1)

    def test_same_scan_or_gap_cannot_manufacture_contraction(self):
        tracker=EligibilityTracker()
        for d in (.8,.7,.6):self.assertEqual(tracker.observe([self.candidate(d)],1)[0],[])
        self.assertEqual(tracker.observe([self.candidate(.5)],20)[0],[])

    def test_sixty_second_contraction_is_observable(self):
        tracker=EligibilityTracker();found=[]
        for scan in range(1,12):found,_,_=tracker.observe([self.candidate(.85-scan*.006)],scan)
        self.assertEqual(len(found),1)
