from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import deque
import argparse,json,math
from research.caterpillar.caterpillar.sources import Archives
from research.caterpillar.caterpillar.h1 import H1Tracker

SYMBOL="WLD"; START=500.; MARGIN=.20; LEV=25.; FEE=4.5/10000; SLIP=2/10000

def h1bars(src,day):
 it,_=src.trades(SYMBOL,day); d={}
 for t in it:
  h=math.floor(t.ts/3600)*3600;b=d.get(h)
  if b is None:d[h]={"open_ts":h,"available_ts":h+3600,"open":t.price,"high":t.price,"low":t.price,"close":t.price,"volume":t.quantity,"timeframe":"1h","interval_minutes":60}
  else:b["high"]=max(b["high"],t.price);b["low"]=min(b["low"],t.price);b["close"]=t.price;b["volume"]+=t.quantity
 return d
def imb(q,now,sec):
 xs=[x for x in q if x[0]>=now-sec];buy=sum(x[2] for x in xs if x[3]==1);sell=sum(x[2] for x in xs if x[3]==-1);n=len(xs)
 return ((buy-sell)/(buy+sell) if buy+sell else None,n,buy,sell)
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 day=datetime(2026,11,2,tzinfo=timezone.utc);prev=day-timedelta(days=1);end=day+timedelta(days=1);src=Archives(a.cache)
 bars={**h1bars(src,prev),**h1bars(src,day)};it,meta=src.trades(SYMBOL,day)
 h=H1Tracker(4);local=None
 for k in sorted(bars):
  if k>=day.timestamp():break
  ev,_=h.seed(bars[k],day.timestamp())
  for loc,stage,reason in ev:
   if stage=="CONFIRMED":local=loc
 cash=START;pos=None;watch=None;trades=[];q=deque();nextb=day.timestamp()+3600;last=None;maxeq=START;maxdd=0.;entries=0;reentries=0;next_eval=day.timestamp()
 for t in it:
  last=t
  while t.ts>=nextb and nextb<end.timestamp():
   b=bars.get(nextb-3600)
   if b:
    ev,_=h.seed(b,nextb)
    for loc,stage,reason in ev:
     if stage=="CONFIRMED":local=loc
   nextb+=3600
  q.append((t.ts,t.price*t.quantity,t.price*t.quantity,int(t.side)))
  while q and q[0][0]<t.ts-300:q.popleft()
  if t.ts < next_eval: continue
  next_eval=t.ts+10.0
  i60,n60,b60,s60=imb(q,t.ts,60);i180,n180,b180,s180=imb(q,t.ts,180);i300,n300,b300,s300=imb(q,t.ts,300)
  if i60 is None:continue
  side=1 if local and local.kind=="LOW" else -1 if local and local.kind=="HIGH" else 0
  aligned=lambda x:side*x
  coverage=(q[-1][0]-q[0][0]) if q else 0
  vals=[aligned(i60)]
  if coverage>=180 and i180 is not None: vals.append(aligned(i180))
  if coverage>=300 and i300 is not None: vals.append(aligned(i300))
  counter=bool(side and vals and all(x<0 for x in vals))
  resumed=bool(side and vals and all(x>0 for x in vals))
  control=resumed
  if pos and side and side!=pos["side"]:
   counter=True
  if pos and counter:
   fill=t.price*(1-pos["side"]*SLIP);gross=pos["qty"]*(fill-pos["entry"])*pos["side"];ef=pos["qty"]*fill*FEE;pnl=gross-pos["entry_fee"]-ef;cash+=gross-ef
   trades.append({**pos,"exit":fill,"closed":t.ts,"pnl":pnl,"fees":pos["entry_fee"]+ef,"reason":"EXECUTED_FLOW_COUNTER_TAKEOVER","mfe":pos["mfe"],"mae":pos["mae"]})
   watch={"side":pos["side"],"opposite_epoch":t.ts};pos=None
  elif not pos and side and ((watch is None and control) or (watch and watch["side"]==side and t.ts>watch["opposite_epoch"] and resumed)):
   kind="ENTRY" if watch is None else "REENTRY";margin=max(0,cash)*MARGIN;notional=margin*LEV;fill=t.price*(1+side*SLIP);qty=notional/fill;fee=notional*FEE;cash-=fee
   pos={"side":side,"entry":fill,"opened":t.ts,"qty":qty,"margin":margin,"notional":notional,"entry_fee":fee,"kind":kind,"mfe":0.,"mae":0.};entries+=kind=="ENTRY";reentries+=kind=="REENTRY";watch=None
  if pos:
   exitmark=t.price*(1-pos["side"]*SLIP);net=pos["qty"]*(exitmark-pos["entry"])*pos["side"]-pos["entry_fee"]-pos["qty"]*exitmark*FEE;pos["mfe"]=max(pos["mfe"],net);pos["mae"]=min(pos["mae"],net)
   eq=cash+pos["qty"]*(t.price-pos["entry"])*pos["side"];maxeq=max(maxeq,eq);maxdd=max(maxdd,1-eq/maxeq)
 if pos and last:
  fill=last.price*(1-pos["side"]*SLIP);gross=pos["qty"]*(fill-pos["entry"])*pos["side"];ef=pos["qty"]*fill*FEE;pnl=gross-pos["entry_fee"]-ef;cash+=gross-ef;trades.append({**pos,"exit":fill,"closed":last.ts,"pnl":pnl,"fees":pos["entry_fee"]+ef,"reason":"EOD_MARK","mfe":pos["mfe"],"mae":pos["mae"]})
 pnl=sum(x["pnl"] for x in trades);r={"symbol":SYMBOL,"date":"2026-11-02","strategy":"Caterpillar 9ce11ede exact local_order_flow M1/M3/M5 semantics, original 10s runtime cadence","start":START,"final":cash,"pnl":pnl,"return_pct":pnl/START*100,"trades":len(trades),"wins":sum(x["pnl"]>0 for x in trades),"losses":sum(x["pnl"]<=0 for x in trades),"entries":entries,"reentries":reentries,"fees":sum(x["fees"] for x in trades),"max_drawdown_pct":maxdd*100,"mfe_sum":sum(x["mfe"] for x in trades),"mae_sum":sum(x["mae"] for x in trades),"data":meta,"rules":{"counter_takeover":"15s<=-0.15,30s<=-0.10 plus 60s/relative confirmation","resumed":"15s>=0.18,30s>=0.12 plus 60s/relative confirmation","initial_control":"15s>=0.12,30s>=0.08","H1":"confirmed local LOW=LONG HIGH=SHORT"}}
 (a.output/"RESULT.json").write_text(json.dumps(r));(a.output/"TRADES.json").write_text(json.dumps(trades));print("OLD_CATERPILLAR_WLD_RESULT "+json.dumps(r),flush=True)
if __name__=="__main__":main()
