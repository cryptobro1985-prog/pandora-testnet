#!/usr/bin/env python3
import csv, gzip, io, json, math, os, statistics, tempfile, urllib.request
import datetime as dt

SYMBOLS=("INIT","NEAR","GRASS","HYPE")
FEE=0.00045
LEV=25.0
MARGIN_FRACTION=0.20
START_EQUITY=500.0

def f(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None

def field(row,*names):
    low={str(k).lower():v for k,v in row.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None

def trade_epoch(row):
    for k in ("timestamp","time","T","ts"):
        if k in row:
            v=f(row.get(k))
            if v is None: continue
            if v>1e14:return v/1e6
            if v>1e11:return v/1e3
            return v
    return None

def download_day(symbol,date):
    pair=symbol+"USDT"
    name=f"{pair}{date.isoformat()}.csv.gz"
    url=f"https://public.bybit.com/trading/{pair}/{name}"
    req=urllib.request.Request(url,headers={"User-Agent":"pandora-research/1.0","Accept":"*/*"})
    spool=tempfile.SpooledTemporaryFile(max_size=64*1024*1024,mode="w+b")
    with urllib.request.urlopen(req,timeout=90) as r:
        while True:
            chunk=r.read(1024*1024)
            if not chunk:break
            spool.write(chunk)
    spool.seek(0)
    return spool,url

def parse_day(spool,start_epoch,end_epoch):
    out={};accepted=0
    with gzip.GzipFile(fileobj=spool,mode="rb") as gz:
        text=io.TextIOWrapper(gz,encoding="utf-8",errors="replace",newline="")
        reader=csv.DictReader(text)
        for row in reader:
            ts=trade_epoch(row)
            price=f(field(row,"price","p"))
            size=f(field(row,"size","qty","v"))
            side=str(field(row,"side","S") or "").strip().lower()
            if ts is None or price is None or size is None or price<=0 or size<=0:continue
            if ts<start_epoch or ts>=end_epoch:continue
            if side not in ("buy","sell","b","a"):continue
            idx=int(ts//15)*15
            b=out.get(idx)
            if b is None:
                b={"t":idx,"o":price,"h":price,"l":price,"c":price,"buy":0.0,"sell":0.0,"count":0}
                out[idx]=b
            b["h"]=max(b["h"],price);b["l"]=min(b["l"],price);b["c"]=price
            notion=price*size
            if side in ("buy","b"):b["buy"]+=notion
            else:b["sell"]+=notion
            b["count"]+=1;accepted+=1
    return out,accepted

def merge(dst,src):
    for k,b in src.items():
        if k not in dst:
            dst[k]=dict(b);continue
        a=dst[k]
        a["h"]=max(a["h"],b["h"]);a["l"]=min(a["l"],b["l"]);a["c"]=b["c"]
        a["buy"]+=b["buy"];a["sell"]+=b["sell"];a["count"]+=b["count"]

def bars(buckets,seconds):
    g={}
    for t in sorted(buckets):
        b=buckets[t];k=(t//seconds)*seconds
        x=g.get(k)
        if x is None:
            x={"t":k,"o":b["o"],"h":b["h"],"l":b["l"],"c":b["c"]}
            g[k]=x
        else:
            x["h"]=max(x["h"],b["h"]);x["l"]=min(x["l"],b["l"]);x["c"]=b["c"]
    return [g[k] for k in sorted(g)]

def h1_events(h1):
    ev=[]
    for i in range(5,len(h1)):
        x=h1[i];p=h1[i-1];prior=h1[i-5:i-1]
        if len(prior)<4:continue
        high=p["h"]>=max(z["h"] for z in prior) and x["h"]<p["h"]
        low=p["l"]<=min(z["l"] for z in prior) and x["l"]>p["l"]
        side=1 if low and not high else (-1 if high and not low else 0)
        if side:
            ev.append({"at":int(x["t"]+3600),"entry_side":side,
                       "pivot_type":"LOCAL_LOW" if side>0 else "LOCAL_HIGH",
                       "pivot_price":p["l"] if side>0 else p["h"],
                       "signal_candle_time":int(x["t"]*1000)})
    return ev

def flow(buckets,t,side):
    def vol(sec):
        buy=sell=0.0;count=0
        start=t-sec+15
        for q in range(start,t+1,15):
            b=buckets.get(q)
            if b:
                buy+=b["buy"];sell+=b["sell"];count+=b["count"]
        return buy,sell,count
    def imb(b,s):
        return (b-s)/(b+s) if b+s else 0.0
    b15,s15,c15=vol(15);b30,s30,c30=vol(30);b60,s60,c60=vol(60)
    a15=side*imb(b15,s15);a30=side*imb(b30,s30);a60=side*imb(b60,s60)
    active=c15>=2 and c30>=4 and c60>=5
    return {
        "active":active,"a15":a15,"a30":a30,"a60":a60,
        "counter_takeover":active and a15<=-0.15 and a30<=-0.10 and (a15<=a60-0.08 or a60<=-0.08),
        "resumed":active and a15>=0.18 and a30>=0.12 and a60>=0.08,
        "aligned_control":active and a15>=0.12 and a30>=0.08,
        "counts":(c15,c30,c60)
    }

def pnl(pos,mark):
    move=pos["side"]*(mark/pos["entry"]-1.0)
    return pos["notional"]*(move-2*FEE)

def run(date):
    target=dt.date.fromisoformat(date)
    warm=target-dt.timedelta(days=1)
    start=dt.datetime.combine(target,dt.time(0),tzinfo=dt.timezone.utc).timestamp()
    end=start+86400
    warm_start=dt.datetime.combine(warm,dt.time(0),tzinfo=dt.timezone.utc).timestamp()

    data={};coverage={}
    for s in SYMBOLS:
        buckets={};rows=0;files=[]
        for d in (warm,target):
            try:
                sp,url=download_day(s,d)
                try:
                    part,n=parse_day(sp,warm_start,end)
                finally:
                    sp.close()
                merge(buckets,part);rows+=n;files.append({"date":d.isoformat(),"ok":True,"rows":n,"url":url})
            except Exception as e:
                files.append({"date":d.isoformat(),"ok":False,"error":type(e).__name__+":"+str(e)[:120]})
        data[s]={"buckets":buckets,"events":h1_events(bars(buckets,3600))}
        coverage[s]={"rows":rows,"files":files,"buckets15":len(buckets)}

    if any(not data[s]["buckets"] for s in SYMBOLS):
        raise RuntimeError("missing_symbol_data:"+json.dumps({s:coverage[s] for s in SYMBOLS}))

    cash=START_EQUITY;positions={};watches={};anchors={};event_i={s:0 for s in SYMBOLS}
    last_price={};trades=[];peak=START_EQUITY;max_dd=0.0
    all_times=sorted(set(t for s in SYMBOLS for t in data[s]["buckets"] if start<=t<end))

    def mtm():
        return cash+sum(pnl(p,last_price.get(s,p["entry"])) for s,p in positions.items())

    def open_pos(symbol,side,mark,kind,signal,reentries=0):
        nonlocal cash
        eq=mtm();used=sum(p["margin"] for p in positions.values());free=eq-used
        margin=max(.01,eq*MARGIN_FRACTION)
        if free+1e-9<margin:return False
        positions[symbol]={"symbol":symbol,"side":side,"entry":mark,"margin":margin,
                           "notional":margin*LEV,"opened":t,"kind":kind,
                           "signal_candle_time":signal,"reentries":reentries}
        return True

    def close_pos(symbol,mark,reason):
        nonlocal cash
        p=positions.pop(symbol);x=pnl(p,mark);cash+=x
        trades.append({"symbol":symbol,"side":p["side"],"kind":p["kind"],"opened":p["opened"],
                       "closed":t,"entry":p["entry"],"exit":mark,"pnl":x,"reason":reason,
                       "reentries":p.get("reentries",0)})
        return p,x

    for t in all_times:
        for s in SYMBOLS:
            b=data[s]["buckets"].get(t)
            if b:last_price[s]=b["c"]
            evs=data[s]["events"];i=event_i[s]
            while i<len(evs) and evs[i]["at"]<=t:
                anchors[s]=evs[i];i+=1
            event_i[s]=i

        for s in SYMBOLS:
            mark=last_price.get(s);a=anchors.get(s)
            if mark is None or a is None:continue
            side=int(a["entry_side"])
            p=positions.get(s);w=watches.get(s)

            if p:
                if side==-int(p["side"]):
                    old,_=close_pos(s,mark,"OPPOSITE_H1")
                    watches.pop(s,None)
                    open_pos(s,side,mark,"INITIAL",a["signal_candle_time"],0)
                    continue
                pr=flow(data[s]["buckets"],t,int(p["side"]))
                if pr["counter_takeover"]:
                    old,_=close_pos(s,mark,"COUNTER_TAKEOVER")
                    watches[s]={"side":old["side"],"exit_price":mark,"exit_t":t,
                                "origin_signal":old["signal_candle_time"],"reentries":old.get("reentries",0),
                                "pullback_extreme":mark,"counter_seen":True,"counter_t":t}
                continue

            if w:
                if side==-int(w["side"]):
                    watches.pop(s,None)
                    open_pos(s,side,mark,"INITIAL",a["signal_candle_time"],0)
                    continue
                ws=int(w["side"])
                if ws>0:w["pullback_extreme"]=min(float(w["pullback_extreme"]),mark)
                else:w["pullback_extreme"]=max(float(w["pullback_extreme"]),mark)
                pr=flow(data[s]["buckets"],t,ws)
                if pr["counter_takeover"]:
                    w["counter_seen"]=True;w["counter_t"]=t
                recovery=ws*(mark/float(w["pullback_extreme"])-1.0)
                if w.get("counter_seen") and t>int(w.get("counter_t") or 0) and pr["resumed"] and recovery>=0.0005:
                    if open_pos(s,ws,mark,"REENTRY",w["origin_signal"],int(w.get("reentries",0))+1):
                        watches.pop(s,None)
                continue

            # Initial H1 entry once there is a confirmed anchor.
            # A position/watch is what prevents repeated entries on the same anchor.
            open_pos(s,side,mark,"INITIAL",a["signal_candle_time"],0)

        eq=mtm();peak=max(peak,eq)
        if peak>0:max_dd=max(max_dd,(peak-eq)/peak)

    final_eq=mtm()
    closed=sum(x["pnl"] for x in trades)
    wins=sum(x["pnl"]>0 for x in trades)
    re=[x for x in trades if x["kind"]=="REENTRY"]
    initial=[x for x in trades if x["kind"]=="INITIAL"]
    gains=sum(x["pnl"] for x in trades if x["pnl"]>0)
    losses=-sum(x["pnl"] for x in trades if x["pnl"]<0)
    by={}
    for s in SYMBOLS:
        xs=[x for x in trades if x["symbol"]==s]
        rs=[x for x in xs if x["kind"]=="REENTRY"]
        by[s]={"trades":len(xs),"wins":sum(x["pnl"]>0 for x in xs),"pnl":round(sum(x["pnl"] for x in xs),4),
               "reentries":len(rs),"reentry_wins":sum(x["pnl"]>0 for x in rs),
               "reentry_pnl":round(sum(x["pnl"] for x in rs),4)}
    result={
      "date":date,"source":"official_bybit_public_trade_archives","symbols":list(SYMBOLS),
      "policy":"H1 + 15s/30s/60s counter-takeover -> exhaustion -> resumed control",
      "thresholds":{"counter":{"15s":-0.15,"30s":-0.10,"60s_rule":"15s<=60s-0.08 OR 60s<=-0.08"},
                    "resume":{"15s":0.18,"30s":0.12,"60s":0.08},"price_recovery":0.0005},
      "starting_equity":START_EQUITY,"final_equity":round(final_eq,4),
      "return_pct":round((final_eq/START_EQUITY-1)*100,4),
      "realized_pnl":round(closed,4),"open_pnl":round(final_eq-cash,4),
      "closed_trades":len(trades),"wins":wins,"win_rate":round(wins/len(trades),4) if trades else None,
      "profit_factor":round(gains/losses,4) if losses else None,"max_drawdown_pct":round(max_dd*100,4),
      "initial_trades":len(initial),"initial_pnl":round(sum(x["pnl"] for x in initial),4),
      "reentries":len(re),"reentry_wins":sum(x["pnl"]>0 for x in re),
      "reentry_win_rate":round(sum(x["pnl"]>0 for x in re)/len(re),4) if re else None,
      "reentry_pnl":round(sum(x["pnl"] for x in re),4),
      "open_positions":{s:{"side":p["side"],"kind":p["kind"],"entry":p["entry"],"mark":last_price.get(s),
                           "unrealized":round(pnl(p,last_price.get(s,p["entry"])),4)} for s,p in positions.items()},
      "per_symbol":by,"coverage":coverage,
      "trades":trades
    }
    print("RESULT_JSON="+json.dumps(result,separators=(",",":"),default=str))
    print(json.dumps({k:result[k] for k in ("date","starting_equity","final_equity","return_pct","realized_pnl","open_pnl","closed_trades","wins","win_rate","max_drawdown_pct","reentries","reentry_wins","reentry_win_rate","reentry_pnl","per_symbol")},indent=2))
    return result

if __name__=="__main__":
    run(os.getenv("BACKTEST_DATE","2026-10-30"))
