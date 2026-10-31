import sys,os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv,gzip,io,json,math,statistics,urllib.request,datetime as dt
from collections import defaultdict
from h1_structure_legacy import analyze as h1_analyze

SYMBOLS=("INIT","NEAR","GRASS","HYPE")
DAY=dt.date(2026,10,30)
WARM=DAY-dt.timedelta(days=1)
FEE=0.00045
LEV=25.0
MARGIN_FRAC=0.20

def day_epoch(d):
    return dt.datetime.combine(d,dt.time(0),tzinfo=dt.timezone.utc).timestamp()

START=day_epoch(DAY); END=day_epoch(DAY+dt.timedelta(days=1)); WARM_START=day_epoch(WARM)

def dl(symbol,d):
    pair=symbol+"USDT"
    name=f"{pair}{d.isoformat()}.csv.gz"
    url=f"https://public.bybit.com/trading/{pair}/{name}"
    req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-research/1.0"})
    with urllib.request.urlopen(req,timeout=90) as r:
        return r.read(),url

def f(x):
    try:
        v=float(x); return v if math.isfinite(v) else None
    except: return None

def field(row,*names):
    low={str(k).lower():v for k,v in row.items()}
    for n in names:
        if n.lower() in low:return low[n.lower()]
    return None

def ts_of(row):
    for k in ("timestamp","time","T","ts"):
        if k in row:
            v=f(row.get(k))
            if v is None: continue
            if v>1e14:return v/1e6
            if v>1e11:return v/1e3
            return v
    return None

def parse(blob):
    buckets={}
    with gzip.GzipFile(fileobj=io.BytesIO(blob),mode="rb") as gz:
        rd=csv.DictReader(io.TextIOWrapper(gz,encoding="utf-8",errors="replace",newline=""))
        for row in rd:
            ts=ts_of(row); px=f(field(row,"price","p")); qty=f(field(row,"size","qty","v"))
            side=str(field(row,"side","S") or "").strip().lower()
            if ts is None or px is None or qty is None or px<=0 or qty<=0: continue
            if ts<WARM_START or ts>=END: continue
            if side not in ("buy","sell","b","a"): continue
            t=int(ts//15)*15
            b=buckets.get(t)
            if b is None:
                b={"t":t,"o":px,"h":px,"l":px,"c":px,"buy":0.0,"sell":0.0,"count":0}
                buckets[t]=b
            b["h"]=max(b["h"],px); b["l"]=min(b["l"],px); b["c"]=px
            notional=px*qty
            if side in ("buy","b"): b["buy"]+=notional
            else: b["sell"]+=notional
            b["count"]+=1
    return buckets

def merge(dst,src):
    for k,b in src.items():
        if k not in dst: dst[k]=b; continue
        a=dst[k]; a["h"]=max(a["h"],b["h"]); a["l"]=min(a["l"],b["l"]); a["c"]=b["c"]
        a["buy"]+=b["buy"]; a["sell"]+=b["sell"]; a["count"]+=b["count"]

def bars(buckets,seconds):
    out={}
    for t in sorted(buckets):
        b=buckets[t]; k=(t//seconds)*seconds
        x=out.get(k)
        if x is None:
            x={"t":int(k*1000),"T":int((k+seconds)*1000-1),"o":b["o"],"h":b["h"],"l":b["l"],"c":b["c"],"v":b["buy"]+b["sell"]}
            out[k]=x
        else:
            x["h"]=max(x["h"],b["h"]); x["l"]=min(x["l"],b["l"]); x["c"]=b["c"]; x["v"]+=b["buy"]+b["sell"]
    return [out[k] for k in sorted(out)]

def vol(buckets,t,sec):
    buy=sell=0.0; count=0
    start=t-sec+15
    for q in range(start,t+1,15):
        b=buckets.get(q)
        if b:
            buy+=b["buy"]; sell+=b["sell"]; count+=b["count"]
    return buy,sell,count

def imb(b,s):
    return (b-s)/(b+s) if b+s else 0.0

def flow_profile(buckets,t,side):
    b15,s15,c15=vol(buckets,t,15); b30,s30,c30=vol(buckets,t,30); b60,s60,c60=vol(buckets,t,60)
    short=side*imb(b15,s15); medium=side*imb(b30,s30); minute=side*imb(b60,s60)
    active=(c15>=2 and c30>=4 and c60>=5 and b15+s15>0 and b30+s30>0)
    return {
      "15":short,"30":medium,"60":minute,"active":active,
      "counter_takeover":bool(active and short<=-.15 and medium<=-.10 and (short<=minute-.08 or minute<=-.08)),
      "resumed":bool(active and short>=.18 and medium>=.12 and minute>=.08),
      "aligned_control":bool(active and short>=.12 and medium>=.08),
    }

def pnl(pos,px):
    move=pos["side"]*(px/pos["entry"]-1.0)
    return pos["notional"]*(move-2*FEE)

data={}; h1bars={}
for sym in SYMBOLS:
    b={}
    for d in (WARM,DAY):
        blob,url=dl(sym,d); merge(b,parse(blob))
    data[sym]=b; h1bars[sym]=bars(b,3600)
    print("LOADED",sym,len(b),flush=True)

# Causal H1 anchor cache updated only when a new closed H1 becomes available.
anchors={}; last_h1_hour={s:None for s in SYMBOLS}
positions={}; watches={}; last_price={}
cash=500.0; peak=500.0; maxdd=0.0; trades=[]; entry_log=[]

all_times=sorted(set(t for s in SYMBOLS for t in data[s] if START<=t<END))

def mtm():
    return cash + sum(pnl(p,last_price.get(s,p["entry"])) for s,p in positions.items())

for t in all_times:
    for s in SYMBOLS:
        b=data[s].get(t)
        if b:last_price[s]=b["c"]

    # refresh causal H1 once per hour, using only candles closed before t
    hour=int(t//3600)
    for s in SYMBOLS:
        if last_h1_hour[s]!=hour:
            rows=[r for r in h1bars[s] if r["T"] <= int(t*1000)-1000]
            if rows:
                try:
                    a=h1_analyze(rows,int(t*1000),s)
                    if a.get("ready") and a.get("anchor_confirmed") and int(a.get("entry_side") or 0) in (-1,1):
                        anchors[s]=a
                except Exception:
                    pass
            last_h1_hour[s]=hour

    # exits and watch updates first
    for s in SYMBOLS:
        px=last_price.get(s); a=anchors.get(s)
        if px is None or a is None: continue
        side=int(a.get("entry_side") or 0)
        pos=positions.get(s)
        if pos:
            # opposite confirmed H1 ends regime
            if side==-int(pos["side"]):
                reason="opposite_confirmed_h1_local"
            else:
                prof=flow_profile(data[s],t,int(pos["side"]))
                reason="executed_flow_profit_flip_exit" if prof["counter_takeover"] and pnl(pos,px)>0 else ("executed_flow_risk_flip_exit" if prof["counter_takeover"] else None)
            if reason:
                realized=pnl(pos,px); cash+=realized
                trades.append({"symbol":s,"kind":pos["kind"],"side":pos["side"],"entry":pos["entry"],"exit":px,"opened":pos["opened"],"closed":t,"pnl":realized,"reason":reason})
                if reason!="opposite_confirmed_h1_local":
                    watches[s]={"side":pos["side"],"exit_price":px,"exit_t":t,"phase":"WAIT_PULLBACK","counter_seen":False,"extreme":px}
                positions.pop(s,None)
            continue
        w=watches.get(s)
        if w:
            if side==-int(w["side"]):
                watches.pop(s,None); continue
            p=flow_profile(data[s],t,int(w["side"]))
            w["extreme"]=min(w["extreme"],px) if w["side"]>0 else max(w["extreme"],px)
            if p["counter_takeover"]:
                w["counter_seen"]=True; w["phase"]="WAIT_RESUMPTION"; w["last_opp_t"]=t
            if w["phase"]=="WAIT_RESUMPTION" and w["counter_seen"] and p["resumed"]:
                recovery=w["side"]*(px/w["extreme"]-1.0)
                if recovery>=.0005:
                    eq=mtm(); margin=max(.01,eq*MARGIN_FRAC)
                    used=sum(x["margin"] for x in positions.values())
                    if eq-used+1e-9>=margin:
                        positions[s]={"side":w["side"],"entry":px,"margin":margin,"notional":margin*LEV,"opened":t,"kind":"REENTRY"}
                        entry_log.append({"symbol":s,"kind":"REENTRY","t":t,"px":px,"f15":p["15"],"f30":p["30"],"f60":p["60"],"recovery":recovery})
                        watches.pop(s,None)
            continue

    # initial entry: exact old behavior = confirmed H1 local itself is permission
    for s in SYMBOLS:
        if s in positions or s in watches: continue
        px=last_price.get(s); a=anchors.get(s)
        if px is None or a is None: continue
        side=int(a.get("entry_side") or 0)
        if side not in (-1,1): continue
        eq=mtm(); margin=max(.01,eq*MARGIN_FRAC)
        used=sum(x["margin"] for x in positions.values())
        if eq-used+1e-9>=margin:
            positions[s]={"side":side,"entry":px,"margin":margin,"notional":margin*LEV,"opened":t,"kind":"INITIAL"}
            entry_log.append({"symbol":s,"kind":"INITIAL","t":t,"px":px})

    eq=mtm(); peak=max(peak,eq)
    if peak>0:maxdd=max(maxdd,(peak-eq)/peak)

# Close all at end for comparable realized final equity.
for s,pos in list(positions.items()):
    px=last_price[s]; realized=pnl(pos,px); cash+=realized
    trades.append({"symbol":s,"kind":pos["kind"],"side":pos["side"],"entry":pos["entry"],"exit":px,"opened":pos["opened"],"closed":END,"pnl":realized,"reason":"end_of_test"})
positions.clear()

wins=sum(1 for x in trades if x["pnl"]>0)
re=[x for x in trades if x["kind"]=="REENTRY"]
rw=sum(1 for x in re if x["pnl"]>0)
g=sum(x["pnl"] for x in trades if x["pnl"]>0); l=-sum(x["pnl"] for x in trades if x["pnl"]<0)
per={}
for s in SYMBOLS:
    xs=[x for x in trades if x["symbol"]==s]; rs=[x for x in xs if x["kind"]=="REENTRY"]
    per[s]={"trades":len(xs),"wins":sum(x["pnl"]>0 for x in xs),"pnl":round(sum(x["pnl"] for x in xs),4),
            "reentries":len(rs),"reentry_wins":sum(x["pnl"]>0 for x in rs),"reentry_pnl":round(sum(x["pnl"] for x in rs),4)}
result={
 "source":"official_bybit_public_trade_archives",
 "window":[DAY.isoformat(),(DAY+dt.timedelta(days=1)).isoformat()],
 "symbols":SYMBOLS,"starting_equity":500.0,"final_equity":round(cash,4),
 "pnl":round(cash-500,4),"return_pct":round((cash/500-1)*100,3),
 "max_drawdown_pct":round(maxdd*100,3),"closed_trades":len(trades),"wins":wins,
 "win_rate_pct":round(100*wins/len(trades),2) if trades else None,
 "profit_factor":round(g/l,3) if l>0 else None,
 "reentries":len(re),"reentry_wins":rw,"reentry_win_rate_pct":round(100*rw/len(re),2) if re else None,
 "reentry_pnl":round(sum(x["pnl"] for x in re),4),
 "per_symbol":per,
 "policy":{"counter_takeover":"15s<=-0.15,30s<=-0.10,and(15s<=60s-0.08 or 60s<=-0.08)",
           "resumed":"15s>=0.18,30s>=0.12,60s>=0.08",
           "price_recovery":">=0.05% from pullback extreme",
           "initial_entry":"confirmed legacy H1 local immediate"},
 "best_reentries":sorted(re,key=lambda x:x["pnl"],reverse=True)[:10],
 "worst_reentries":sorted(re,key=lambda x:x["pnl"])[:10],
}
print("REENTRY_DD97_RESULT "+json.dumps(result,separators=(",",":"),default=str),flush=True)
open("reentry_dd97_result.json","w").write(json.dumps(result,indent=2,default=str))
