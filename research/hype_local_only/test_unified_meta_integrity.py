#!/usr/bin/env python3
"""Regression guards for the research-only tri-brain meta split and regime."""
import unittest
from research.hype_local_only.train_unified_local_intelligence_v2 import fit_meta, _minute_regime

def candidate(cid,ts,y,stage=60):
    return {
        "candidate_id":str(cid),"ts":int(ts),"stage":int(stage),
        "side":"LOW" if int(cid)%2 else "HIGH","y":float(y),
        "p_fin":0.15+0.6*float(y),"p_quant":0.2+0.5*float(y),
        "p_river":0.2+0.4*float(y),"p_tree":0.12+0.6*float(y),
        "p_timeline":0.2+0.3*float(y),"p_cortex":0.2+0.6*float(y),
        "regime_score":0.1,"regime_accel":0.01
    }

class UnifiedIntegrityTest(unittest.TestCase):
    def test_meta_fit_calibration_no_duplicate_candidate(self):
        rows=[]
        start=1792713600000
        for i in range(28):
            ts=start+i*3600000
            for stage in (60,180,300):
                rows.append(candidate(i,ts,i%3==0,stage))
        model,threshold,metrics,info=fit_meta(rows)
        self.assertEqual(info["candidate_id_overlap"],0)
        self.assertEqual(info["meta_train_rows"]%3,0)
        self.assertEqual(info["cal_rows"]%3,0)
        self.assertEqual(info["purge_ms"],10800000)
        self.assertLessEqual(info["meta_train_candidates"]+info["cal_candidates"],28)
        self.assertTrue(0<=threshold<=1)
        self.assertIn("precision",metrics)

    def test_insufficient_class_is_rejected(self):
        rows=[candidate(i,1792713600000+i*3600000,0) for i in range(30)]
        with self.assertRaises(RuntimeError):
            fit_meta(rows)

    def test_completed_contiguous_regime(self):
        rows=[]
        for i in range(500):
            rows.append({"bar_end_ms":(i+1)*60000,"close":100.0+i*.01,"gap":False})
        times=[r["bar_end_ms"] for r in rows]
        z=_minute_regime(rows,times,times[-1])
        self.assertIn("discovery__market_ret_480m",z)
        self.assertGreater(z["discovery__market_regime_score"],0)

    def test_gap_quarantines_8h_and_regime(self):
        rows=[]
        for i in range(500):
            rows.append({"bar_end_ms":(i+1)*60000,"close":100.0+i*.01,"gap":i==260})
        times=[r["bar_end_ms"] for r in rows]
        z=_minute_regime(rows,times,times[-1])
        self.assertNotIn("discovery__market_ret_480m",z)
        self.assertNotIn("discovery__market_regime_score",z)
        self.assertIn("discovery__market_ret_60m",z)

    def test_timestamp_jump_quarantines_long_regime(self):
        rows=[]
        for i in range(500):
            ts=(i+1)*60000+(60000 if i>=200 else 0)
            rows.append({"bar_end_ms":ts,"close":100.0+i*.01,"gap":False})
        times=[r["bar_end_ms"] for r in rows]
        z=_minute_regime(rows,times,times[-1])
        self.assertNotIn("discovery__market_ret_480m",z)
        self.assertNotIn("discovery__market_regime_score",z)

if __name__=="__main__":
    unittest.main()
