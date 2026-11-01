"""Hourly selection stays fixed; freshness freeze must recover after reconnect."""
import os,unittest
from unittest.mock import patch
import pandora_scanner
from pandora_scanner import LiveScanner

class FrozenHourlyV3Tests(unittest.TestCase):
 def test_recover_from_stale_ticker_without_reselecting_top_five(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}),patch.object(
      pandora_scanner,"ACTIVE_FLOW_EXPERIMENT","PANDORA_PUMP_STRUCTURE_V3_400"):
   sc=LiveScanner()
   snapshot=dict(experiment="PANDORA_PUMP_STRUCTURE_V3_400",
     selected_symbols=["A","B","C","D","E"],selected_at=1000,
     next_refresh_at=4600,selection_frozen=True,observations_ready=False,
     reason="fresh_bybit_tickers_required_for_hourly_top5")
   sc.restore(snapshot)
   instruments={s:{} for s in ["A","B","C","D","E","Z"]}
   frozen=sc.rank(instruments,lambda *_:{},(),1200)
   self.assertTrue(frozen["selection_frozen"])
   self.assertEqual(frozen["selected_symbols"],snapshot["selected_symbols"])
   sc.ingest(dict(symbol="AUSDT",lastPrice="1.25",turnover24h="2000000",
       price24hPcnt=".03"),1201000,received=1201)
   sc.ingest(dict(symbol="ZUSDT",lastPrice="2",turnover24h="4000000",
       price24hPcnt=".95"),1201000,received=1201)
   healed=sc.rank(instruments,lambda *_:{},(),1202)
   self.assertFalse(healed["selection_frozen"])
   self.assertTrue(healed["observations_ready"])
   self.assertEqual(healed["selected_symbols"],snapshot["selected_symbols"])
   self.assertEqual(healed["next_refresh_at"],4600)
   self.assertNotIn("reason",healed)
   lost=sc.rank(instruments,lambda *_:{},(),1220)
   self.assertTrue(lost["selection_frozen"])
   self.assertEqual(lost["selected_symbols"],snapshot["selected_symbols"])
   self.assertFalse(lost["observations_ready"])

if __name__=="__main__":unittest.main()
