#!/usr/bin/env python3
import unittest
from research.hype_unified_intelligence.entry_path_targets import label_path,validate_future

START=1790000000000

def bars(ohlc):
    return [{"bar_end_ms":START+(i+1)*60000,"low":lo,"high":hi,
             "close":cl,"gap":False} for i,(lo,hi,cl) in enumerate(ohlc)]

class PathLabelTest(unittest.TestCase):
    def test_long_favorable_first(self):
        q=bars([(100,100.6,100.5),(100.3,101,100.8),(100.7,101.2,101)])
        x=label_path(START,100,q,horizons=(3,),target_bps=(50,))
        self.assertEqual(x["horizons"]["3"]["LONG"]["hit_target_before_adverse"]["50"],1)
        self.assertEqual(x["horizons"]["3"]["SHORT"]["hit_target_before_adverse"]["50"],0)
        self.assertFalse(x["future_used_as_predictor"])

    def test_same_bar_dual_touch_fails_closed(self):
        q=bars([(99.5,100.6,100),(99.7,100.2,100),(99.9,100.1,100)])
        x=label_path(START,100,q,horizons=(3,),target_bps=(50,))
        self.assertEqual(x["horizons"]["3"]["LONG"]["hit_target_before_adverse"]["50"],0)
        self.assertEqual(x["horizons"]["3"]["SHORT"]["hit_target_before_adverse"]["50"],0)

    def test_data_gap_is_rejected(self):
        q=bars([(100,100.6,100.5),(100.3,101,100.8),(100.7,101.2,101)])
        q[1]["bar_end_ms"]+=60000
        with self.assertRaises(ValueError):
            label_path(START,100,q,horizons=(3,))

    def test_short_and_long_mfe_mae(self):
        q=bars([(99,100.3,99.4),(98.7,99.7,99),(98.1,99.5,98.5)])
        x=label_path(START,100,q,horizons=(3,))
        z=x["horizons"]["3"]
        self.assertGreater(z["SHORT"]["mfe_bps"],z["LONG"]["mfe_bps"])
        self.assertGreater(z["LONG"]["mae_bps"],z["SHORT"]["mae_bps"])

    def test_future_never_used_as_input(self):
        x=label_path(START,100,bars([(100,100,100)]*3),horizons=(3,))
        self.assertEqual(x["role"],"TARGET_EVAL_ONLY")
        self.assertIsNone(x["horizons"]["3"]["LONG"]["hit_target_before_adverse"]["50"])

if __name__=="__main__":unittest.main()
