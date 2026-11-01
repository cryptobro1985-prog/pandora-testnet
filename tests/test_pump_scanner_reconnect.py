"""Scanner must restore trading readiness after reconnect without midhour rotation."""
import os, unittest
from unittest.mock import patch
from pandora_scanner import LiveScanner
from pandora_flow_v2_live import EXPERIMENT

class ScannerReconnectV3(unittest.TestCase):
 def test_frozen_snapshot_unfreezes_only_after_fresh_selected_tickers(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}):
   sc=LiveScanner()
   symbols=["ESPORTS","LYN","INIT","NIULAI","FOUR"]
   instruments={s:{} for s in symbols+["CHALLENGER"]}
   sc.restore(dict(experiment=EXPERIMENT,selected_symbols=symbols,
      selected_at=1000,next_refresh_at=4600,selected=[],selection_frozen=True,
      observations_ready=False))
   before=sc.rank(instruments,lambda *_:{},("INIT",),1001)
   self.assertTrue(before["selection_frozen"])
   self.assertEqual(before["selected_symbols"],symbols)
   for sym in symbols[:-1]:
    self.assertTrue(sc.ingest(dict(symbol=sym+"USDT",lastPrice="1",
     turnover24h="2000000",price24hPcnt=".2"),1010000,received=1010))
   partial=sc.rank(instruments,lambda *_:{},(),1010)
   self.assertTrue(partial["selection_frozen"])
   self.assertTrue(sc.ingest(dict(symbol="FOURUSDT",lastPrice="1",
    turnover24h="2000000",price24hPcnt=".2"),1011000,received=1011))
   recovered=sc.rank(instruments,lambda *_:{},(),1011)
   self.assertFalse(recovered["selection_frozen"])
   self.assertTrue(recovered["observations_ready"])
   self.assertEqual(recovered["selected_symbols"],symbols)
   self.assertEqual(recovered["next_refresh_at"],4600)
   self.assertEqual(recovered["events"],[])
   # A challenger cannot rotate within the existing hourly window.
   self.assertTrue(sc.ingest(dict(symbol="CHALLENGERUSDT",lastPrice="1",
    turnover24h="30000000",price24hPcnt="1.2"),1012000,received=1012))
   unchanged=sc.rank(instruments,lambda *_:{},(),1012)
   self.assertEqual(unchanged["selected_symbols"],symbols)
 def test_recovered_tickers_expire_and_freeze_again(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}):
   sc=LiveScanner();instruments={"A":{}}
   sc.restore(dict(experiment=EXPERIMENT,selected_symbols=["A"],next_refresh_at=4600,
    selection_frozen=True))
   sc.ingest(dict(symbol="AUSDT",lastPrice="1",turnover24h="2000000",price24hPcnt=".1"),
    1000000,received=1000)
   self.assertFalse(sc.rank(instruments,lambda *_:{},(),1000)["selection_frozen"])
   self.assertTrue(sc.rank(instruments,lambda *_:{},(),1017)["selection_frozen"])
if __name__=="__main__":unittest.main()
