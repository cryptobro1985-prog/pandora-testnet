"""Regression: main-paper adapter keeps legacy contract off and pump structure on."""
import os,unittest
from unittest.mock import patch
import pandora_flow_v2_live as adapter
from tests.test_pump_structure_v3 import tape

class PumpAdapterTest(unittest.TestCase):
 def setUp(self):
  with adapter._PUMP_LOCK:adapter._PUMP_STATES.clear()
 def test_opt_in_long_then_no_short_on_shallow_pullback(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}):
   a=tape(1000,100)
   self.assertEqual(adapter.entry_candidate("ESPORTS",a)["side"],1)
   adapter.entry_candidate("ESPORTS",tape(1001,110))
   dip=tape(1002,109.8,-.7,-.002)
   self.assertFalse(adapter.entry_candidate("ESPORTS",dip)["eligible"])
   self.assertEqual(adapter._PUMP_STATES["ESPORTS"]["phase"],"PUMP")
 def test_verified_sell_needs_new_execution(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}):
   adapter.entry_candidate("ESPORTS",tape(1000,100))
   adapter.entry_candidate("ESPORTS",tape(1001,110))
   decline=tape(1002,106,-.8,-.04)
   self.assertFalse(adapter.entry_candidate("ESPORTS",decline)["eligible"])
   follow=tape(1003,105,-.8,-.02)
   self.assertEqual(adapter.entry_candidate("ESPORTS",follow)["side"],-1)
 def test_observing_on_restart_recovers_confirmed_entry_pump(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}):
   entry=dict(phase="PUMP",pump_seen=True,peak_price=110.,
     peak_support=108.,observed_price=109.,last_event_epoch=1000.)
   observing=dict(phase="OBSERVING",pump_seen=False,peak_price=105.,
     peak_support=105.,observed_price=105.,last_event_epoch=1001.)
   with adapter._PUMP_LOCK:
    adapter._PUMP_STATES["ESPORTS"]=dict(observing)
   p=dict(symbol="ESPORTS",side=1,entry=100.,features={
     "candidate_selection":{"structure":dict(entry)},
     "v3_structure_snapshot":dict(observing)})
   f=tape(1002,105.5,.05,.001)
   self.assertIsNone(adapter.exit_reason(p,105.5,f))
   saved=p["features"]["v3_structure_snapshot"]
   self.assertEqual(saved["phase"],"PUMP")
   self.assertTrue(saved["pump_seen"])
   self.assertEqual(saved["peak_price"],110.)
   self.assertEqual(saved["peak_support"],108.)
 def test_persisted_position_restores_structure(self):
  with patch.dict(os.environ,{"PANDORA_FLOW_V2":"1","PANDORA_PUMP_V3":"1"}):
   adapter.entry_candidate("ESPORTS",tape(1000,100))
   adapter.entry_candidate("ESPORTS",tape(1001,110))
   position=dict(symbol="ESPORTS",side=1,entry=100.,features={})
   self.assertIsNone(adapter.exit_reason(position,109.8,tape(1002,109.8,-.7,-.002)))
   saved=position["features"]["v3_structure_snapshot"]
   with adapter._PUMP_LOCK:adapter._PUMP_STATES.clear()
   position2=dict(symbol="ESPORTS",side=1,entry=100.,features=dict(v3_structure_snapshot=saved))
   self.assertEqual(adapter.exit_reason(position2,106,tape(1003,106,-.8,-.04)),
     "confirmed_counter_move_exit")
if __name__=="__main__":unittest.main()
