import unittest
from research.bybit_options.labeler import label_signal

class LabelerTests(unittest.TestCase):
    def setUp(self):
        self.signal={"ts_ms":100000,"expiry_ms":100000+4000000,"symbol":"BTC-X-C","action":"BUY_OPTION"}
        self.points=[
            {"ts_ms":100000,"bid":8.0,"ask":10.0,"mark":9.0,"iv":0.5,"underlying":100.0},
            {"ts_ms":160000,"bid":14.0,"ask":15.0,"mark":14.5,"iv":0.6,"underlying":102.0},
            {"ts_ms":280000,"bid":7.0,"ask":9.0,"mark":8.0,"iv":0.4,"underlying":99.0}
        ]
    def test_bid_ask_and_mfe(self):
        result=label_signal(self.signal,self.points)
        o=result["outcomes"]["60s"]
        self.assertEqual(o["gross_return_pct"],40.0)
        self.assertEqual(o["mfe_pct"],40.0)
        self.assertEqual(o["time_to_mfe_seconds"],60.0)
        self.assertEqual(o["round_trip_spread_pct"],20.0)
    def test_missing_future_is_censored(self):
        result=label_signal(self.signal,self.points)
        self.assertEqual(result["outcomes"]["900s"]["status"],"censored_no_fresh_bid")
    def test_future_only_entry_is_censored(self):
        result=label_signal(self.signal,[{**self.points[0],"ts_ms":300001}])
        self.assertEqual(result["entry_status"],"censored_no_fresh_ask")

if __name__=="__main__":
    unittest.main()
