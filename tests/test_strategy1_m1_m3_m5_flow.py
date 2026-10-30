import unittest
from local_order_flow import flow_profile, pressure_exit, update_watch, reentry_ready, initial_entry_candidate

def flow(i60, i180, i300, epoch=1000.0):
    return {
        "trade_data_fresh": True,
        "latest_trade_age_seconds": 0.5,
        "trade_coverage_seconds": 320,
        "volume_window_end_epoch": epoch,
        "flow_imbalance": i60,
        "flow_imbalance_15s": i60,
        "flow_imbalance_30s": i180,
        "flow_imbalance_180s": i180,
        "flow_imbalance_300s": i300,
        "price_return_300s": 0.01 if i300 > 0 else -0.01,
        "trade_count_15s": 5,
        "trade_count_30s": 7,
        "trade_count_60s": 8,
        "buy_volume_15s": 60, "sell_volume_15s": 40,
        "buy_volume_30s": 120, "sell_volume_30s": 80,
        "observed_notional_60s": 1000,
        "trade_count_180s": 20,
        "trade_count_300s": 40,
    }

class Strategy1FlowTests(unittest.TestCase):
    def analysis(self, side=1):
        return {"ready": True, "anchor_confirmed": True,
                "h1_direction_anchor": {"pivot_type":"LOCAL_LOW" if side>0 else "LOCAL_HIGH"},
                "entry_side": side, "entry_blocked": False}

    def test_entry_only_when_h1_side_predominates_on_m1_m3_m5(self):
        self.assertTrue(initial_entry_candidate("HYPE",self.analysis(1),None,flow(.18,.12,.10),1000)["eligible"])
        self.assertFalse(initial_entry_candidate("HYPE",self.analysis(1),None,flow(.18,.12,-.01),1000)["eligible"])

    def test_exit_immediately_when_opposite_m1_predominates(self):
        pos={"side":1,"entry":100.0,"features":{"mfe_price_move":0.03}}
        self.assertEqual(pressure_exit(pos,None,101.0,flow(-.25,-.14,-.08)),
                         "executed_flow_m1_opposite_control_exit")
        self.assertEqual(pressure_exit(pos,None,101.0,flow(-.25,-.14,.02)),
                         "executed_flow_m1_opposite_control_exit")
        self.assertIsNone(pressure_exit(pos,None,101.0,flow(.25,-.14,-.08)))

    def test_mfe_size_and_giveback_do_not_create_exit_filter(self):
        counter=flow(-.25,-.14,-.08)
        for mfe,mark in ((0.0,99.8),(0.001,100.0),(0.02,101.0),(0.08,104.0)):
            pos={"side":1,"entry":100.0,"features":{"mfe_price_move":mfe}}
            self.assertEqual(pressure_exit(pos,None,mark,counter),
                             "executed_flow_m1_opposite_control_exit")

    def test_price_response_does_not_gate_buyer_seller_control(self):
        f=flow(.18,.12,.10)
        f["price_return_300s"]=-.02
        self.assertTrue(flow_profile(f,1)["direct_control"])
        self.assertTrue(initial_entry_candidate("HYPE",self.analysis(1),None,f,1000)["eligible"])

    def test_missing_m3_m5_does_not_create_restart_warmup_gate(self):
        f=flow(.18,.12,.10)
        f["trade_coverage_seconds"]=60
        f.pop("flow_imbalance_180s")
        f.pop("flow_imbalance_300s")
        profile=flow_profile(f,1)
        self.assertIsNotNone(profile)
        self.assertTrue(profile["aligned_control"])
        self.assertTrue(initial_entry_candidate("HYPE",self.analysis(1),None,f,1000)["eligible"])

    def test_exit_watch_then_independent_same_side_control_reenters(self):
        watch={"side":1,"exit_price":101.0,"exit_at":"2026-10-29T00:00:00+00:00",
               "context":{"phase":"WAIT_PULLBACK","counter_pressure_seen":False}}
        observed=update_watch(watch,100.0,None,flow(-.25,-.14,-.08,1000.0),1000.0)
        self.assertEqual(observed["context"]["phase"],"WAIT_RESUMPTION")
        self.assertTrue(observed["context"]["counter_pressure_seen"])
        self.assertFalse(reentry_ready(1,None,100.06,observed,flow(.18,.12,.10,1000.0),1001.0))
        self.assertTrue(reentry_ready(1,None,100.06,observed,flow(.18,.12,.10,1002.0),1002.0))

if __name__=="__main__":
    unittest.main()
