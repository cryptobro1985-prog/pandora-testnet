from __future__ import annotations
import csv, gzip, io, json, math, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

START=datetime(2026,10,4,tzinfo=timezone.utc)
END=datetime(2026,11,3,tzinfo=timezone.utc)
DISCOVERY_START=datetime(2026,10,11,tzinfo=timezone.utc).timestamp()
SPLIT=datetime(2026,10,27,tzinfo=timezone.utc).timestamp()
END_TS=END.timestamp()
FEE=0.00055
START_EQUITY=100.0
SL_GRID=[0.005,0.0075,0.01,0.0125,0.015,0.02,0.025,0.03,0.04]
TP_GRID=[0.01,0.015,0.02,0.025,0.03,0.04,0.05,0.06,0.08,0.10,0.12]

def archive_url(day):
    d=day.strftime("%Y-%m-%d")
    return f"https://public.bybit.com/trading/HYPEUSDT/HYPEUSDT{d}.csv.gz"

def load_minutes():
    bars={}
    trade_count=0
    day=START
    while day<END:
        url=archive_url(day)
        req=urllib.request.Request(url,headers={"User-Agent":"hype-ema-macd-research/1.0"})
        with urllib.request.urlopen(req,timeout=90) as resp:
            gz=gzip.GzipFile(fileobj=resp)
            txt=io.TextIOWrapper(gz,newline="")
            rd=csv.DictReader(txt)
            for row in rd:
                ts=float(row["timestamp"])
                p=float(row["price"])
                minute=int(ts//60)*60
                b=bars.get(minute)
                if b is None:
                    bars[minute]=[p,p,p,p,1]
                else:
                    b[1]=max(b[1],p); b[2]=min(b[2],p); b[3]=p; b[4]+=1
                trade_count+=1
        print(json.dumps({"day":day.strftime("%Y-%m-%d"),"minutes_so_far":len(bars),"trades_so_far":trade_count}),flush=True)
        day+=timedelta(days=1)
    rows=[{"ts":k,"open":v[0],"high":v[1],"low":v[2],"close":v[3],"trades":v[4]} for k,v in sorted(bars.items())]
    return rows,trade_count

def h1_from_minutes(minutes):
    groups=defaultdict(list)
    for r in minutes:
        groups[int(r["ts"]//3600)*3600].append(r)
    out=[]
    for h,rs in sorted(groups.items()):
        rs.sort(key=lambda x:x["ts"])
        out.append({"ts":h,"open":rs[0]["open"],"high":max(x["high"] for x in rs),
                    "low":min(x["low"] for x in rs),"close":rs[-1]["close"],"minutes":len(rs)})
    return out

def ema(values,n):
    a=2/(n+1)
    out=[]
    x=None
    for v in values:
        x=v if x is None else a*v+(1-a)*x
        out.append(x)
    return out

def build_signals(h1):
    c=[x["close"] for x in h1]
    e6,e20=ema(c,6),ema(c,20)
    e12,e26=ema(c,12),ema(c,26)
    macd=[a-b for a,b in zip(e12,e26)]
    signals=[]
    for i in range(1,len(h1)-1):
        up=e6[i-1]<=e20[i-1] and e6[i]>e20[i] and macd[i]>0
        dn=e6[i-1]>=e20[i-1] and e6[i]<e20[i] and macd[i]<0
        if not (up or dn):
            continue
        # signal known only after H1 close; enter at next hour
        enter_ts=h1[i]["ts"]+3600
        signals.append({"signal_ts":h1[i]["ts"]+3600,"enter_ts":enter_ts,"side":1 if up else -1,
                        "macd":macd[i],"ema6":e6[i],"ema20":e20[i]})
    return signals

def run(minutes, signals, sl, tp, start_ts, end_ts):
    mins=[r for r in minutes if start_ts<=r["ts"]<end_ts]
    if not mins: return None
    sigs={s["enter_ts"]:s for s in signals if start_ts<=s["enter_ts"]<end_ts}
    equity=START_EQUITY
    peak=equity
    maxdd=0.0
    trades=[]
    pos=None
    for r in mins:
        ts=r["ts"]
        s=sigs.get(ts)
        if s and pos and s["side"]!=pos["side"]:
            ret=pos["side"]*(r["open"]/pos["entry"]-1)-2*FEE
            equity*=max(0.0,1+ret)
            trades.append({"side":pos["side"],"entry":pos["entry"],"exit":r["open"],"ret":ret,"reason":"opposite","entry_ts":pos["ts"],"exit_ts":ts})
            peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak if peak else 1)
            pos=None
        if s and pos is None:
            pos={"side":s["side"],"entry":r["open"],"ts":ts}
        if not pos: continue
        e=pos["entry"]
        if pos["side"]==1:
            stop=e*(1-sl); take=e*(1+tp)
            hit_stop=r["low"]<=stop; hit_take=r["high"]>=take
            if hit_stop:
                x=stop; reason="stop"
            elif hit_take:
                x=take; reason="take"
            else:
                continue
            ret=(x/e-1)-2*FEE
        else:
            stop=e*(1+sl); take=e*(1-tp)
            hit_stop=r["high"]>=stop; hit_take=r["low"]<=take
            if hit_stop:
                x=stop; reason="stop"
            elif hit_take:
                x=take; reason="take"
            else:
                continue
            ret=(e/x-1)-2*FEE
        equity*=max(0.0,1+ret)
        trades.append({"side":pos["side"],"entry":e,"exit":x,"ret":ret,"reason":reason,"entry_ts":pos["ts"],"exit_ts":ts})
        peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak if peak else 1)
        pos=None
    if pos:
        r=mins[-1]
        ret=pos["side"]*(r["close"]/pos["entry"]-1)-2*FEE
        equity*=max(0.0,1+ret)
        trades.append({"side":pos["side"],"entry":pos["entry"],"exit":r["close"],"ret":ret,"reason":"period_end","entry_ts":pos["ts"],"exit_ts":r["ts"]})
        peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak if peak else 1)
    wins=sum(t["ret"]>0 for t in trades)
    gp=sum(max(t["ret"],0) for t in trades); gl=-sum(min(t["ret"],0) for t in trades)
    return {"final":equity,"return_pct":(equity/START_EQUITY-1)*100,"trades":len(trades),"wins":wins,
            "win_rate":wins/len(trades)*100 if trades else 0.0,"max_dd_pct":maxdd*100,
            "profit_factor":gp/gl if gl>0 else None,
            "stops":sum(t["reason"]=="stop" for t in trades),"takes":sum(t["reason"]=="take" for t in trades),
            "opposite":sum(t["reason"]=="opposite" for t in trades),"detail":trades}

def main():
    minutes,trade_count=load_minutes()
    h1=h1_from_minutes(minutes)
    signals=build_signals(h1)
    print(json.dumps({"dataset":{"minutes":len(minutes),"trades":trade_count,"h1":len(h1),"signals_total":len(signals),
                                 "first":minutes[0]["ts"],"last":minutes[-1]["ts"]}},sort_keys=True),flush=True)
    results=[]
    for sl in SL_GRID:
        for tp in TP_GRID:
            d=run(minutes,signals,sl,tp,DISCOVERY_START,SPLIT)
            if d and d["trades"]>=2:
                results.append({"sl":sl,"tp":tp,**{k:v for k,v in d.items() if k!="detail"}})
    results.sort(key=lambda x:(x["final"],-x["max_dd_pct"]),reverse=True)
    top=results[:10]
    winner=top[0]
    oos=run(minutes,signals,winner["sl"],winner["tp"],SPLIT,END_TS)
    full=run(minutes,signals,winner["sl"],winner["tp"],DISCOVERY_START,END_TS)
    # neighbor stability around winner
    near=[x for x in results if abs(x["sl"]-winner["sl"])<=0.0051 and abs(x["tp"]-winner["tp"])<=0.0101][:20]
    payload={"assumptions":{"ema":"6/20 H1 close","macd":"12/26 line sign on H1","entry":"next H1 open","fee_per_side":FEE,
                             "same_minute_tp_sl":"stop-first conservative","position":"100% equity at 1x, compounded"},
             "discovery":{"start":"2026-10-11","end_exclusive":"2026-10-27","top10":top,"winner":winner},
             "oos":{"start":"2026-10-27","end_exclusive":"2026-11-03",**{k:v for k,v in oos.items() if k!="detail"}},
             "full":{"start":"2026-10-11","end_exclusive":"2026-11-03",**{k:v for k,v in full.items() if k!="detail"}},
             "winner_trades":full["detail"],"neighbor_candidates":near}
    print("RESULT_JSON="+json.dumps(payload,separators=(",",":"),sort_keys=True),flush=True)
    with open("hype_ema_macd_30d_result.json","w") as f: json.dump(payload,f,indent=2,sort_keys=True)

if __name__=="__main__":
    main()
