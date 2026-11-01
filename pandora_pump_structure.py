"""Causal pump-support state: accepted Bybit trades only, PAPER-only decisions."""
import copy,math,os
EXPERIMENT="PANDORA_PUMP_STRUCTURE_V3_400"

def enabled():return os.getenv("PANDORA_FLOW_V2")=="1" and os.getenv("PANDORA_PUMP_V3","1")!="0"
def n(x,default=0):
 try:
  z=float(x)
  return z if math.isfinite(z) else default
 except (TypeError,ValueError,OverflowError):return default
def w(f,k):return ((f or {}).get("windows") or {}).get(str(k)) or {}
def event(f):return n((f or {}).get("decision_event_epoch") or (f or {}).get("latest_trade_epoch"))
def buyer(f):
 a,b=w(f,15),w(f,30)
 return bool(f and f.get("trade_data_fresh") and f.get("evidence_ready") and a.get("complete") and b.get("complete")
  and n(a.get("trade_count"))>=2 and n(b.get("trade_count"))>=4
  and n(a.get("imbalance"))>=.20 and n(b.get("imbalance"))>=.12
  and n(b.get("price_return"))>0 and not f.get("buy_absorbed"))
def seller(f):
 a,b,c=w(f,15),w(f,30),w(f,60)
 return bool(f and f.get("trade_data_fresh") and f.get("evidence_ready") and a.get("complete") and b.get("complete")
  and n(a.get("trade_count"))>=3 and n(b.get("trade_count"))>=6
  and n(a.get("imbalance"))<=-.25 and n(b.get("imbalance"))<=-.20
  and n(a.get("sell_volume"))>=1.7*n(a.get("buy_volume"))
  and n(b.get("sell_volume"))>n(b.get("buy_volume"))
  and n(b.get("price_return"))<0
  and (n(c.get("volume_velocity"))<=0 or n(a.get("volume_velocity"))>=.7*n(c.get("volume_velocity")))
  and not f.get("sell_absorbed"))
def advance(old,f,mark):
 s=copy.deepcopy(old or {})
 if not f or not f.get("trade_data_fresh") or not mark or mark<=0:return s
 e=event(f)
 if not e or e<=n(s.get("last_event_epoch")):return s
 price=float(mark);a,b,c=w(f,15),w(f,30),w(f,60)
 peak=n(s.get("peak_price"));support=n(s.get("peak_support"))
 rising=n(c.get("price_return"))>0 and n(c.get("imbalance"))>0
 buy=buyer(f);sell=seller(f)
 s.update(last_event_epoch=e,observed_price=price,buy_confirmed=buy,sell_confirmed=sell)
 if not peak or price>peak:
  s.update(phase="PUMP" if (rising or buy or peak) else "OBSERVING",
   peak_price=price,peak_support=n(b.get("price_low"),price) or price,
   pump_seen=bool(rising or buy or s.get("pump_seen")),break_confirmed=False,break_event_epoch=0,break_price=None)
  return s
 if s.get("phase")=="CORRECTION_CONFIRMED":
  if buy and (n(c.get("price_return"))>0 or (support>0 and price>support)):
   s.update(phase="PUMP",break_confirmed=False,break_event_epoch=0)
  else:
   s.update(correction_low=min(n(s.get("correction_low"),price),price))
  return s
 if rising or buy:s["pump_seen"]=True
 decline=(peak-price)/peak
 threshold=max(.002,1.5*n(a.get("price_range_fraction")))
 if s.get("pump_seen") and support>0 and price<support and decline>=threshold and sell:
  s.update(phase="CORRECTION_CONFIRMED",break_confirmed=True,
   break_event_epoch=e,break_price=price,correction_low=price,
   break_basis="PRIOR_PUMP_SUPPORT_AND_SELL_VOLUME")
 else:s.update(phase="PUMP" if s.get("pump_seen") else "OBSERVING",break_confirmed=False)
 return s
def candidate(symbol,f,state,last_exit_event=0):
 s=state or {};e=event(f);phase=s.get("phase")
 if not f or not f.get("trade_data_fresh"):return dict(symbol=symbol,side=0,eligible=False,reason="TAPE_STALE")
 if not e or e<=n(last_exit_event):return dict(symbol=symbol,side=0,eligible=False,reason="WAIT_POST_CLOSE_EVENT")
 if phase=="CORRECTION_CONFIRMED":
  if seller(f) and e>n(s.get("break_event_epoch")) and n(s.get("observed_price"))<=n(s.get("break_price"),float("inf")):
   return dict(symbol=symbol,side=-1,eligible=True,reason="CONFIRMED_SELL_AFTER_PUMP_SUPPORT_BREAK",structure=copy.deepcopy(s))
  return dict(symbol=symbol,side=0,eligible=False,reason="WAIT_NEW_SELL_AFTER_BREAK")
 if phase=="PUMP" and buyer(f):
  return dict(symbol=symbol,side=1,eligible=True,reason="PUMP_BUY_CONTINUATION",structure=copy.deepcopy(s))
 return dict(symbol=symbol,side=0,eligible=False,
  reason="HOLD_PUMP_NO_SHORT_ON_PULLBACK" if s.get("pump_seen") else "WAIT_PUMP_CONTEXT")
def exit_reason(position,mark,f,state):
 feat=position.setdefault("features",{});s=state or {};e=event(f)
 if not f or not f.get("trade_data_fresh") or not mark:
  feat["exit_decision"]={"reason":"DATA_UNCERTAIN","structure":s.get("phase")};return None
 if e<=n(feat.get("v3_last_exit_event")):return None
 feat["v3_last_exit_event"]=e
 if int(position["side"])>0:
  confirmed=s.get("phase")=="CORRECTION_CONFIRMED" and seller(f)
  reason="PUMP_SUPPORT_BROKEN_SELL_VOLUME" if confirmed else "HOLD_LONG_MICRO_PULLBACK"
 else:
  confirmed=buyer(f) and (s.get("phase")=="PUMP" or n(w(f,60).get("price_return"))>0 or
     (n(s.get("peak_support"))>0 and mark>n(s.get("peak_support"))))
  reason="BUY_CONTROL_RECLAIM_SHORT_EXIT" if confirmed else "HOLD_SHORT_BOUNCE"
 feat["exit_decision"]=dict(reason=reason,phase=s.get("phase"),peak=s.get("peak_price"),
  support=s.get("peak_support"),break_price=s.get("break_price"),mark=mark,event=e,
  buy=f.get("buy_notional"),sell=f.get("sell_notional"))
 return "confirmed_counter_move_exit" if confirmed else None
