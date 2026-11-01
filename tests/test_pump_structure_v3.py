"""No SHORT on a temporary sell pullback; verified break needs new trades."""
import unittest
from pandora_pump_structure import advance,candidate,exit_reason

def tape(event,price,bias=.6,ret=.015,volume=100.):
 sell=bias<0
 def window(seconds):
  return dict(complete=True,trade_count=40,imbalance=bias,
   buy_volume=10 if sell else 80,sell_volume=80 if sell else 10,
   volume_velocity=volume,price_return=ret,
   price_low=price*(.995 if not sell else 1.01),
   price_range_fraction=.001)
 return dict(trade_data_fresh=True,evidence_ready=True,decision_event_epoch=event,
  last_price=price,windows={str(k):window(k) for k in (5,15,30,60,180)},
  flow_imbalance=bias,buy_absorbed=False,sell_absorbed=False,
  buy_notional=800 if not sell else 200,sell_notional=200 if not sell else 800)

class PumpStructureTests(unittest.TestCase):
 def test_long_on_strong_buy(self):
  f=tape(1000,100)
  state=advance({},f,100)
  self.assertTrue(candidate("ESPORTS",f,state)["eligible"])
  self.assertEqual(candidate("ESPORTS",f,state)["side"],1)
 def test_sell_pullback_not_short(self):
  s=advance({},tape(1000,100),100)
  s=advance(s,tape(1001,110),110)
  f=tape(1002,109.8,-.7,-.002)
  s=advance(s,f,109.8)
  self.assertEqual(s["phase"],"PUMP")
  self.assertFalse(candidate("ESPORTS",f,s)["eligible"])
  self.assertIsNone(exit_reason(dict(symbol="ESPORTS",side=1,features={}),109.8,f,s))
 def test_break_then_new_sell_event_allows_short(self):
  s=advance({},tape(1000,100),100)
  s=advance(s,tape(1001,110),110)
  f=tape(1002,106,-.8,-.04)
  s=advance(s,f,106)
  self.assertEqual(s["phase"],"CORRECTION_CONFIRMED")
  self.assertFalse(candidate("ESPORTS",f,s)["eligible"])
  self.assertEqual(exit_reason(dict(symbol="ESPORTS",side=1,features={}),106,f,s),
    "confirmed_counter_move_exit")
  f2=tape(1003,105,-.8,-.03)
  s=advance(s,f2,105)
  self.assertEqual(candidate("ESPORTS",f2,s)["side"],-1)
 def test_short_bounce_holds(self):
  s=dict(phase="CORRECTION_CONFIRMED",peak_price=110.,peak_support=109.,
    break_event_epoch=1002,break_price=106)
  pos=dict(symbol="ESPORTS",side=-1,features={})
  self.assertIsNone(exit_reason(pos,105.2,tape(1003,105.2,.1,.001),s))
 def test_no_data_short(self):
  f=tape(1000,100,-.8,-.02)
  self.assertFalse(candidate("ESPORTS",f,{})["eligible"])
 def test_stale_hold(self):
  f=tape(1001,90,-.8,-.1);f["trade_data_fresh"]=False
  s=advance({},f,90)
  self.assertFalse(candidate("ESPORTS",f,s)["eligible"])
  self.assertIsNone(exit_reason(dict(symbol="ESPORTS",side=1,features={}),90,f,s))
if __name__=="__main__":unittest.main()
