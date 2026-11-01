"""Historical application H1 readiness gate, retired by pure executed flow."""
import copy
import unittest
import app
from h1_structure import analyze
from tests.test_pandora_restoration import bars,BASE,H

class RuntimeH1GateV1(unittest.TestCase):
    def setUp(self):self.saved=copy.deepcopy(app.S)
    def tearDown(self):app.S.clear();app.S.update(self.saved)

    def test_verified_closed_hour_does_not_expire_after_90_seconds(self):
        stamp=(BASE+6*H+1000)/1000
        a=analyze(bars(),stamp*1000)
        meta={k:a.get(k) for k in ('entry_side','signal_candle_time','pivot_candle_time','last_candle_time')}
        meta['verified_at']=stamp
        app.S['_pandora_h1_runtime_verified']={'BTC':meta}
        self.assertTrue(app.pandora_runtime_h1_verified('BTC',a,stamp+300))
        self.assertFalse(app.pandora_runtime_h1_verified('BTC',a,stamp+H/1000))

