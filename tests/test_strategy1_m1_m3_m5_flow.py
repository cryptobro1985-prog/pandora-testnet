import unittest
from local_order_flow import flow_profile, pressure_exit, update_watch, reentry_ready, initial_entry_candidate

def flow(i60, i180, i300, epoch=1000.0):
    return {
        "trade_data_fresh": True,
        "latest_trade_age_seconds": 0.5,
        "volume_window_end_epoch": epoch,
        "flow_imbalance": i60,
        "flow_imbalance_180s": i180,
        "flow_imbalance_300s": i300,
        "trade_count_60s": 8,
        "trade_count_180s": 20,
        "trade_count_300s": 40,
    }

class Strategy1FlowTests(unittest.TestCase):
    def test_confirmed_h1_flow_entry_is_not_blocked_by_m15(self):
        analysis={"ready": True, "anchor_confirmed": True, "h1_direction_anchor": {"pivot_type":"LOCAL_LOW"}, "entry_side":1, "entry_blocked":False}
        executed=flow(0.18,0.12,0.10)
        adverse_m15={"ready": True, "strong_adverse_pressure": True}
        candidate=initial_entry_candidate("HYPE",analysis,adverse_m15,executed,1000.0)
        self.assertTrue(candidate["eligible"], candidate)

    def test_m1_m3_m5_counterflow_plus_mfe_recoil_exits(self):
        pos={"side":1,"entry":100.0,"features":{"mfe_price_move":0.02,"estimated_round_trip_cost_move":0.001}}
        reason=pressure_exit(pos,{"median_range_move":0.008},101.0,flow(-0.25,-0.14,0.02))
        self.assertEqual(reason,"m1_m3_m5_mfe_profit_exit")

    def test_counterflow_without_recoil_does_not_exit(self):
        pos={"side":1,"entry":100.0,"features":{"mfe_price_move":0.0102,"estimated_round_trip_cost_move":0.001}}
        self.assertIsNone(pressure_exit(pos,{"median_range_move":0.008},101.0,flow(-0.25,-0.14,0.02)))

    def test_missing_m5_coverage_blocks_profile(self):
        f=flow(-0.25,-0.14,0.02)
        f.pop("flow_imbalance_300s")
        self.assertIsNone(flow_profile(f,1))

    def test_exit_watch_then_later_resumption_reenters(self):
        watch={"side":1,"exit_price":101.0,"exit_at":"2026-10-29T00:00:00+00:00","context":{"phase":"WAIT_PULLBACK","counter_pressure_seen":False}}
        observed=update_watch(watch,100.0,None,flow(-0.25,-0.14,0.02,1000.0),1000.0)
        self.assertEqual(observed["context"]["phase"],"WAIT_RESUMPTION")
        self.assertTrue(observed["context"]["counter_pressure_seen"])
        self.assertFalse(reentry_ready(1,None,100.06,observed,flow(0.18,0.12,0.10,1000.0),1001.0))
        self.assertTrue(reentry_ready(1,None,100.06,observed,flow(0.18,0.12,0.10,1002.0),1002.0))

if __name__=="__main__":
    unittest.main()
