#!/usr/bin/env python3
import csv,datetime as dt,gzip,json,math,os,urllib.request
from h1_structure_legacy import analyze as h1_analyze

FEE=.00045; LEV=25.0; MARGIN=.20; COST_MOVE=2*FEE+.0004
SYMBOLS=("INIT","NEAR","GRASS","HYPE")
START=dt.date(2026,10,29); END=dt.date(2026,10,31)

COUNTERS=[
 ("C0",0.0,0.0,None),
 ("C08",.08,.05,None),
 ("C12",.12,.08,None),
 ("C18",.18,.10,None),
 ("CFULL12",.12,.08,.05),
 ("CFULL20",.20,.15,.10),
]
RESUMES=[
 ("R0",0.0,0.0,0.0,0.0,0.0),
 ("R08",.08,.05,.03,.0002,.0003),
 ("R12",.12,.08,.08,.0003,.0005),
 ("R20",.20,.15,.10,.0005,.0007),
 ("R30",.30,.20,.15,.0007,.0010),
]
CONFIGS=[{"name":"NO_REENTRY","off":True}]
for cn,c1,c3,c5 in COUNTERS:
 for rn,r1,r3,r5,p5,rebound in RESUMES:
  CONFIGS.append({"name":cn+"_"+rn,"off":False,"c1":c1,"c3":c3,"c5":c5,
                  "r1":r1,"r3":r3,"r5":r5,"p5":p5,"rebound":rebound})

def num(x):
 try:
  y=float(x); return y if math.isfinite(y) else None
 except Exception:return None

def field(row,*names):
 low={str(k).lower():v for k,v in row.items()}
 for n in names:
  if n.lower() in low:return low[n.lower()]
 return None

def ts_value(row):
 for k in ("timestamp","time","T","ts"):
  if k in row:
   v=num(row.get(k))
   if v is None:continue
   if v>1e14:return v/1e6
   if v>1e11:return v/1e3
   return v
 return None

def download(symbol,date):
 pair=symbol+"USDT";name=f"{pair}{date.isoformat()}.csv.gz"
 url=f"https://public.bybit.com/trading/{pair}/{name}";path="/tmp/"+name
 if not os.path.exists(path) or os.path.getsize(path)<50:
  req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-research/1.0"})
  with urllib.request.urlopen(req,timeout=120) as r,open(path,"wb") as out:
   while True:
    z=r.read(1024*1024)
    if not z:break
    out.write(z)
 return path,url

def load_symbol(symbol):
 buckets={};meta=[]
 d=START-dt.timedelta(days=1)
 while d<END:
  path,url=download(symbol,d);n=0
  with gzip.open(path,"rt",encoding="utf-8",errors="replace",newline="") as fh:
   for row in csv.DictReader(fh):
    ts=ts_value(row);px=num(field(row,"price","p"));qty=num(field(row,"size","qty","v"))
    side=str(field(row,"side","S") or "").lower()
    if ts is None or px is None or qty is None or px<=0 or qty<=0 or side not in ("buy","sell","b","a"):continue
    t=int(ts//5)*5
    b=buckets.get(t)
    if b is None:
     b={"t":t,"o":px,"h":px,"l":px,"c":px,"buy":0.0,"sell":0.0,"count":0,"vol":0.0,"last_ts":ts}
     buckets[t]=b
    b["h"]=max(b["h"],px);b["l"]=min(b["l"],px);b["c"]=px;b["last_ts"]=max(b["last_ts"],ts)
    notion=px*qty
    if side in ("buy","b"):b["buy"]+=notion
    else:b["sell"]+=notion
    b["count"]+=1;b["vol"]+=qty;n+=1
  meta.append({"date":d.isoformat(),"trades":n,"bytes":os.path.getsize(path),"url":url});d+=dt.timedelta(days=1)
 return buckets,meta

def h1_rows(buckets):
 g={}
 for t in sorted(buckets):
  b=buckets[t];k=(t//3600)*3600;x=g.get(k)
  if x is None:g[k]={"t":k*1000,"T":k*1000+3599999,"o":b["o"],"h":b["h"],"l":b["l"],"c":b["c"],"v":b["vol"]}
  else:x["h"]=max(x["h"],b["h"]);x["l"]=min(x["l"],b["l"]);x["c"]=b["c"];x["v"]+=b["vol"]
 return [g[k] for k in sorted(g)]

def flow_series(buckets,start_ts,end_ts):
 out={}; first=min(buckets) if buckets else int(start_ts)
 last_trade=None
 for t in range(int(start_ts//5)*5-300,int(end_ts//5)*5,5):
  if t in buckets:last_trade=buckets[t]["last_ts"]
  age=(t+5-last_trade) if last_trade is not None else 9999
  def win(sec):
   buy=sell=0.0;count=0;rows=[]
   for q in range(t-sec+5,t+1,5):
    b=buckets.get(q)
    if b:
     buy+=b["buy"];sell+=b["sell"];count+=b["count"];rows.append(b)
   total=buy+sell
   return ((buy-sell)/total if total else 0.0),count,rows
  i1,c1,r1=win(60);i3,c3,r3=win(180);i5,c5,r5=win(300)
  p5=None
  if r5:
   p0=r5[0]["o"];p1=r5[-1]["c"]
   if p0>0:p5=p1/p0-1.0
  out[t]={"fresh":-1<=age<=15,"age":age,"m1":i1,"m3":i3,"m5":i5,"p5":p5,
          "c1":c1,"c3":c3,"c5":c5,"event":last_trade,
          "coverage":max(0,(t+5)-first)}
 return out

def confirmed(a):
 return isinstance(a,dict) and a.get("ready") and a.get("anchor_confirmed") and a.get("h1_direction_anchor") and int(a.get("entry_side") or 0) in (-1,1) and not a.get("entry_blocked")

def build_anchors(h1,flows,start_ts,end_ts):
 candidates={}
 for t in range(int(start_ts//3600)*3600,int(end_ts//3600)*3600+3600,3600):
  try:a=h1_analyze(h1,int((t+5)*1000),"X")
  except Exception:a=None
  candidates[t]=a if confirmed(a) else None
 active=None;out={}
 for t in range(int(start_ts//5)*5,int(end_ts//5)*5,5):
  if t%3600==0:
   a=candidates.get(t)
   if a:
    if active is None:active=a
    else:
     ps=int(active.get("entry_side") or 0);ns=int(a.get("entry_side") or 0)
     pt=int(active.get("signal_candle_time") or 0);nt=int(a.get("signal_candle_time") or 0)
     if ns==ps and nt>=pt:active=a
     elif ns==-ps and nt>pt:
      f=flows.get(t) or {};p5=f.get("p5")
      if f.get("fresh") and f.get("coverage",0)>=300 and p5 is not None and ns*f["m1"]>0 and ns*f["m3"]>0 and ns*f["m5"]>0 and ns*p5>0:
       active=a
  out[t]=active
 return out

def aligned(flow,side):
 if not flow or not flow.get("fresh") or flow.get("coverage",0)<300 or flow.get("p5") is None:return None
 return {"m1":side*flow["m1"],"m3":side*flow["m3"],"m5":side*flow["m5"],"p5":side*flow["p5"],"event":flow.get("event")}

def initial_ready(a):
 return bool(a and a["m1"]>0 and a["m3"]>0 and a["m5"]>0 and a["p5"]>0)

def counter_ready(a,cfg):
 if not a:return False
 if not (a["m1"]<=-cfg["c1"] and a["m3"]<=-cfg["c3"]):return False
 return cfg["c5"] is None or a["m5"]<=-cfg["c5"]

def resume_ready(a,cfg,rebound):
 return bool(a and a["m1"]>=cfg["r1"] and a["m3"]>=cfg["r3"] and a["m5"]>=cfg["r5"] and a["p5"]>=cfg["p5"] and rebound>=cfg["rebound"])

def gross(pos,mark):return pos["notional"]*pos["side"]*(mark/pos["entry"]-1.0)
def fee(pos):return pos["notional"]*2*FEE
def net(pos,mark):return gross(pos,mark)-fee(pos)

def simulate(data,start_date,days,cfg):
 st=dt.datetime.combine(start_date,dt.time(),tzinfo=dt.timezone.utc).timestamp()
 en=dt.datetime.combine(start_date+dt.timedelta(days=days),dt.time(),tzinfo=dt.timezone.utc).timestamp()
 cash=500.0;positions={};watches={};last_px={};trades=[];peak=500.0;maxdd=0.0
 def mtm():return cash+sum(net(p,last_px.get(s,p["entry"])) for s,p in positions.items())
 def free():return mtm()-sum(p["margin"] for p in positions.values())
 def openp(s,side,mark,t,kind,watch=None):
  eq=mtm();margin=max(.01,eq*MARGIN)
  if eq<=0 or free()+1e-9<margin:return False
  positions[s]={"symbol":s,"side":side,"entry":mark,"margin":margin,"notional":margin*LEV,
                "leverage":LEV,"opened_t":t,"kind":kind,"mfe":0.0,"mae":0.0,"watch":watch}
  if kind=="REENTRY":watches.pop(s,None)
  return True
 def closep(s,mark,t,reason):
  nonlocal cash
  p=positions.pop(s);g=gross(p,mark);f=fee(p);v=g-f;cash+=v
  row={**p,"exit":mark,"closed_t":t,"gross":g,"fees":f,"pnl":v,"reason":reason};trades.append(row)
  watches[s]={"side":p["side"],"exit_price":mark,"exit_t":t,"reentries":(p.get("watch") or {}).get("reentries",0)+(1 if p["kind"]=="REENTRY" else 0),
              "ctx":{"phase":"WAIT_PULLBACK","seen":False,"extreme":mark,"opp_event":None}}
 for t in range(int(st//5)*5,int(en//5)*5,5):
  for s in SYMBOLS:
   b=data[s]["buckets"].get(t)
   if b:last_px[s]=b["c"]
  for s in SYMBOLS:
   mark=last_px.get(s);anchor=data[s]["anchors"].get(t);flow=data[s]["flows"].get(t)
   if mark is None or not anchor:continue
   side=int(anchor.get("entry_side") or 0);pos=positions.get(s);watch=watches.get(s);a=aligned(flow,pos["side"] if pos else side)
   if pos:
    move=pos["side"]*(mark/pos["entry"]-1.0);pos["mfe"]=max(pos["mfe"],move);pos["mae"]=min(pos["mae"],move)
    reason=None
    if a:
     fast_counter=a["m1"]<0 and a["m3"]<0
     full_counter=a["m1"]<0 and a["m3"]<0 and a["m5"]<0 and a["p5"]<0
     bankable=pos["mfe"]>=max(.0020,COST_MOVE*1.5)
     giveback=max(0.0,pos["mfe"]-move)
     if bankable and fast_counter and giveback>=max(COST_MOVE,pos["mfe"]*.18):reason="mfe_preservation"
     elif full_counter:reason="risk_exit"
    if move*LEV<=-.95:reason="liquidation_proxy"
    if reason:closep(s,mark,t,reason)
    continue
   if watch:
    if int(watch["side"])==-side:
     watches.pop(s,None);watch=None
    else:
     wside=int(watch["side"]);aa=aligned(flow,wside);ctx=watch["ctx"]
     ctx["extreme"]=min(ctx["extreme"],mark) if wside>0 else max(ctx["extreme"],mark)
     if not cfg.get("off") and counter_ready(aa,cfg):
      ctx["seen"]=True;ctx["phase"]="WAIT_RESUMPTION";ctx["opp_event"]=aa.get("event")
     if not cfg.get("off") and ctx["seen"] and ctx["phase"]=="WAIT_RESUMPTION":
      rebound=wside*(mark/ctx["extreme"]-1.0) if ctx["extreme"]>0 else 0.0
      if resume_ready(aa,cfg,rebound) and aa.get("event") is not None and ctx.get("opp_event") is not None and aa["event"]>ctx["opp_event"]:
       openp(s,wside,mark,t,"REENTRY",watch)
     continue
   aa=aligned(flow,side)
   if initial_ready(aa):openp(s,side,mark,t,"ORDER_FLOW")
  eq=mtm();peak=max(peak,eq)
  if peak>0:maxdd=max(maxdd,(peak-eq)/peak)
 final=mtm();re=[x for x in trades if x["kind"]=="REENTRY"]
 return {"config":cfg["name"],"start":start_date.isoformat(),"days":days,"final_equity":final,"return_pct":(final/500-1)*100,
         "realized_pnl":sum(x["pnl"] for x in trades),"open_pnl":sum(net(p,last_px.get(s,p["entry"])) for s,p in positions.items()),
         "gross_pnl":sum(x["gross"] for x in trades),"fees":sum(x["fees"] for x in trades),
         "trades":len(trades),"wins":sum(x["pnl"]>0 for x in trades),"win_rate":sum(x["pnl"]>0 for x in trades)/len(trades) if trades else None,
         "reentries":len(re),"reentry_wins":sum(x["pnl"]>0 for x in re),"reentry_win_rate":sum(x["pnl"]>0 for x in re)/len(re) if re else None,
         "reentry_pnl":sum(x["pnl"] for x in re),"reentry_gross":sum(x["gross"] for x in re),"reentry_fees":sum(x["fees"] for x in re),
         "avg_reentry_hold_s":sum(x["closed_t"]-x["opened_t"] for x in re)/len(re) if re else None,
         "max_drawdown_pct":maxdd*100}

def main():
 start_ts=dt.datetime.combine(START,dt.time(),tzinfo=dt.timezone.utc).timestamp()
 end_ts=dt.datetime.combine(END,dt.time(),tzinfo=dt.timezone.utc).timestamp()
 data={};coverage={}
 for s in SYMBOLS:
  buckets,meta=load_symbol(s);flows=flow_series(buckets,start_ts,end_ts);h1=h1_rows(buckets);anchors=build_anchors(h1,flows,start_ts,end_ts)
  data[s]={"buckets":buckets,"flows":flows,"h1":h1,"anchors":anchors};coverage[s]=meta
  print("READY",s,len(buckets),flush=True)
 periods=[("D29",dt.date(2026,10,29),1),("D30",dt.date(2026,10,30),1),("BOTH",dt.date(2026,10,29),2)]
 results=[]
 for cfg in CONFIGS:
  rec={"config":cfg["name"]}
  for label,d,days in periods:rec[label]=simulate(data,d,days,cfg)
  results.append(rec)
  print("GRID",cfg["name"],round(rec["BOTH"]["final_equity"],2),round(rec["D29"]["final_equity"],2),round(rec["D30"]["final_equity"],2),rec["BOTH"]["reentries"],flush=True)
 ranked=sorted(results,key=lambda r:(min(r["D29"]["final_equity"],r["D30"]["final_equity"]),r["BOTH"]["final_equity"]),reverse=True)
 out={"research_only":True,"source":"official_bybit_public_trade_archives","symbols":SYMBOLS,
      "logic":"current Strategy1.1 H1/initial/exit; grid only changes re-entry counter/resumption strength",
      "configs":CONFIGS,"coverage":coverage,"results":results,"ranked":ranked}
 print("M1M3M5_GRID_RESULT "+json.dumps({"top":ranked[:10],"no_reentry":next(r for r in results if r["config"]=="NO_REENTRY")},separators=(",",":")),flush=True)
 with open("m1m3m5_grid_result.json","w") as fh:json.dump(out,fh,indent=2)
if __name__=="__main__":main()
