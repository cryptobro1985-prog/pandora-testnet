"""One-week causal Strategy 1 backtest from official Bybit public trade archives.

Research only: never mutates PAPER positions or account state.
Downloads daily public trade CSV.GZ files, reconstructs 15s flow plus M15/H1
bars, and replays the universal H1 -> flow weakening -> pullback -> re-entry
state machine with 20% margin, 25x reference leverage and compounding.
"""
import csv
import concurrent.futures
import datetime as dt
import gzip
import io
import json
import math
import os
import statistics
import tempfile
import threading
import time
import urllib.error
import urllib.request

from local_caterpillar import (
    entry_candidate, pressure_exit, update_watch, reentry_ready,
)

SYMBOLS=("INIT","NEAR","GRASS","HYPE","BTC","ETH","SOL","AR","APT","ZEC","WLD","USELESS","TAO","CHIP","BABY","SPX","LIT","CASHCAT")
FEE=0.00045
LEV=25.0
MARGIN_FRACTION=0.20
STATE={"status":"idle","started_at":None,"finished_at":None,"result":None,"error":None}
LOCK=threading.RLock()


def _f(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except Exception:
        return None


def _trade_epoch(row):
    for k in ("timestamp","time","T","ts"):
        if k in row:
            v=_f(row.get(k))
            if v is None: continue
            if v>1e14: return v/1e6
            if v>1e11: return v/1e3
            return v
    return None


def _field(row,*names):
    low={str(k).lower():v for k,v in row.items()}
    for n in names:
        if n.lower() in low:return low[n.lower()]
    return None


def _download_day(symbol,date):
    pair=symbol+"USDT"
    name=f"{pair}{date.isoformat()}.csv.gz"
    url=f"https://public.bybit.com/trading/{pair}/{name}"
    cache_dir="/tmp/pandora_bybit_archives"
    os.makedirs(cache_dir,exist_ok=True)
    cache_path=os.path.join(cache_dir,name)
    spool=tempfile.SpooledTemporaryFile(max_size=16*1024*1024,mode="w+b")
    total=0
    try:
        if os.path.exists(cache_path) and os.path.getsize(cache_path)>50:
            with open(cache_path,"rb") as f:
                while True:
                    chunk=f.read(1024*1024)
                    if not chunk:break
                    spool.write(chunk);total+=len(chunk)
            spool.seek(0)
            return spool,total,url
        req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-research/1.0","Accept":"*/*"})
        tmp_path=cache_path+".part"
        with urllib.request.urlopen(req,timeout=60) as r, open(tmp_path,"wb") as out:
            while True:
                chunk=r.read(1024*1024)
                if not chunk:break
                spool.write(chunk);out.write(chunk);total+=len(chunk)
        if total<50:raise RuntimeError("archive_too_small")
        os.replace(tmp_path,cache_path)
        spool.seek(0)
        return spool,total,url
    except Exception:
        try:
            if os.path.exists(cache_path+".part"):os.remove(cache_path+".part")
        except Exception:pass
        spool.close()
        raise


def _parse_day(spool,start_epoch,end_epoch):
    out={}
    accepted=0
    spool.seek(0)
    with gzip.GzipFile(fileobj=spool,mode="rb") as gz:
        text=io.TextIOWrapper(gz,encoding="utf-8",errors="replace",newline="")
        reader=csv.DictReader(text)
        for row in reader:
            ts=_trade_epoch(row)
            price=_f(_field(row,"price","p"))
            size=_f(_field(row,"size","qty","v"))
            side=str(_field(row,"side","S") or "").strip().lower()
            if ts is None or price is None or size is None or price<=0 or size<=0:
                continue
            if ts<start_epoch or ts>=end_epoch:
                continue
            if side not in ("buy","sell","b","a"):
                continue
            idx=int(ts//15)*15
            b=out.get(idx)
            if b is None:
                b={"t":idx,"o":price,"h":price,"l":price,"c":price,
                   "buy":0.0,"sell":0.0,"count":0,"volume":0.0}
                out[idx]=b
            b["h"]=max(b["h"],price);b["l"]=min(b["l"],price);b["c"]=price
            notion=price*size
            if side in ("buy","b"):b["buy"]+=notion
            else:b["sell"]+=notion
            b["count"]+=1;b["volume"]+=size;accepted+=1
    return out,accepted


def _merge_buckets(dst,src):
    for k,b in src.items():
        if k not in dst:
            dst[k]=b;continue
        a=dst[k]
        a["h"]=max(a["h"],b["h"]);a["l"]=min(a["l"],b["l"]);a["c"]=b["c"]
        a["buy"]+=b["buy"];a["sell"]+=b["sell"];a["count"]+=b["count"];a["volume"]+=b["volume"]


def _bars(buckets,seconds):
    groups={}
    for t in sorted(buckets):
        b=buckets[t];k=(t//seconds)*seconds
        x=groups.get(k)
        if x is None:
            x={"t":k,"T":k+seconds-0.001,"o":b["o"],"h":b["h"],"l":b["l"],"c":b["c"],"v":b["volume"]}
            groups[k]=x
        else:
            x["h"]=max(x["h"],b["h"]);x["l"]=min(x["l"],b["l"]);x["c"]=b["c"];x["v"]+=b["volume"]
    return [groups[k] for k in sorted(groups)]


def _h1_events(h1):
    events=[]
    for i in range(5,len(h1)):
        x=h1[i];p=h1[i-1];prior=h1[i-5:i-1]
        if len(prior)<4:continue
        high=p["h"]>=max(z["h"] for z in prior) and x["h"]<p["h"]
        low=p["l"]<=min(z["l"] for z in prior) and x["l"]>p["l"]
        side=1 if low and not high else (-1 if high and not low else 0)
        if side:
            events.append({"at":int(x["t"]+3600),"entry_side":side,
                           "pivot_type":"LOCAL_LOW" if side>0 else "LOCAL_HIGH",
                           "pivot_price":p["l"] if side>0 else p["h"],
                           "confirmation_close":x["c"],
                           "signal_candle_time":int(x["t"]*1000),
                           "h1_direction_anchor":True,"ready":True,"entry_blocked":False})
    return events


def _flow(buckets,t,side=None):
    def vol(sec):
        buy=sell=0.0;count=0
        start=t-sec+15
        for q in range(start,t+1,15):
            b=buckets.get(q)
            if b:
                buy+=b["buy"];sell+=b["sell"];count+=b["count"]
        return buy,sell,count
    def imb(b,s):return (b-s)/(b+s) if b+s else 0.0
    b15,s15,c15=vol(15);b30,s30,c30=vol(30);b60,s60,c60=vol(60);b180,s180,c180=vol(180);b300,s300,c300=vol(300)
    latest=None
    for q in range(t,t-61,-15):
        if buckets.get(q) and buckets[q]["count"]:
            latest=q;break
    age=(t-latest) if latest is not None else None
    return {"trade_data_fresh":age is not None and age<=15,
            "latest_trade_age_seconds":age,
            "trade_coverage_seconds":300.0,
            "buy_volume_15s":b15,"sell_volume_15s":s15,"trade_count_15s":c15,
            "buy_volume_30s":b30,"sell_volume_30s":s30,"trade_count_30s":c30,
            "buy_volume_60s":b60,"sell_volume_60s":s60,"trade_count_60s":c60,
            "buy_volume_180s":b180,"sell_volume_180s":s180,"trade_count_180s":c180,"flow_imbalance_180s":imb(b180,s180),
            "buy_volume_300s":b300,"sell_volume_300s":s300,"trade_count_300s":c300,
            "observed_notional_60s":b60+s60,
            "flow_imbalance_15s":imb(b15,s15),"flow_imbalance_30s":imb(b30,s30),
            "flow_imbalance":imb(b60,s60),"flow_imbalance_300s":imb(b300,s300)}


def _m15_at(buckets,full_m15,t,side):
    current=(t//900)*900
    closed=[x for x in full_m15 if x["t"]<current]
    if len(closed)<8:return {"ready":False,"side":side}
    elapsed=t-current+15
    rows=closed[-8:]
    if elapsed>=180:
        bs=[buckets.get(q) for q in range(current,t+1,15)]
        bs=[b for b in bs if b]
        if bs:
            x={"t":current,"T":current+900-0.001,"o":bs[0]["o"],
               "h":max(b["h"] for b in bs),"l":min(b["l"] for b in bs),
               "c":bs[-1]["c"],"v":sum(b["volume"] for b in bs),"partial":True}
            rows=rows+[x]
    if len(rows)<5:return {"ready":False,"side":side}
    x=rows[-1];prev=rows[-2]
    r1=x["c"]/prev["c"]-1
    r2=x["c"]/rows[-3]["c"]-1
    rng=max(x["h"]-x["l"],1e-12)
    body=abs(x["c"]-x["o"])/rng
    cdir=1 if x["c"]>x["o"] else (-1 if x["c"]<x["o"] else 0)
    loc=(x["c"]-x["l"])/rng
    prior_vol=[z["v"] for z in rows[-9:-1] if z.get("v",0)>0]
    av=sum(prior_vol)/len(prior_vol) if prior_vol else 0
    raw=(x["v"]/av) if av>0 else None
    frac=min(1.0,max(.001,elapsed/900.0)) if x.get("partial") else 1.0
    vr=(raw/frac) if raw is not None else None
    adverse=0
    if side*r1<=-.0015:adverse+=1
    if side*r2<=-.0025:adverse+=1
    if cdir==-side and body>=.50:adverse+=1
    if (side>0 and loc<=.30) or (side<0 and loc>=.70):adverse+=1
    if vr is not None and vr>=1.35:adverse+=1
    recovery=0
    if side*r1>=.0012:recovery+=1
    if side*r2>=.0020:recovery+=1
    if cdir==side and body>=.42:recovery+=1
    if (side>0 and loc>=.65) or (side<0 and loc<=.35):recovery+=1
    if vr is not None and vr>=.90:recovery+=1
    med=statistics.median((z["h"]-z["l"])/z["c"] for z in closed[-8:])
    return {"ready":True,"side":side,"observed_at_ms":int((t+15)*1000),
            "return_15m":r1,"return_30m":r2,"body_fraction":body,
            "candle_direction":cdir,"close_location":loc,"volume_ratio":vr,
            "median_range_move":med,"adverse_score":adverse,"recovery_score":recovery,
            "strong_adverse_pressure":adverse>=3 and (side*r1<0 or (cdir==-side and body>=.50)),
            "recovery_confirmed":recovery>=3 and (side*r1>0 or (cdir==side and body>=.42))}


def _stop(position,m15,mark,flow):
    if not m15.get("ready"):return None
    side=position["side"];entry=position["entry"];typ=max(.0005,float(m15.get("median_range_move") or .008))
    adverse=max(0.0,-side*(mark/entry-1))
    soft=max(.0075,min(.0180,typ*1.35))
    i15=float(flow.get("flow_imbalance_15s") or 0)*side
    i30=float(flow.get("flow_imbalance_30s") or 0)*side
    counter=i15<=-.12 and i30<=-.08
    candle=(int(m15.get("candle_direction") or 0)==-side and float(m15.get("body_fraction") or 0)>=.45)
    strong=bool(m15.get("strong_adverse_pressure")) and int(m15.get("adverse_score") or 0)>=3
    if adverse>=soft and candle and (counter or strong):return "confirmed_protective_stop"
    hard=max(.015,min(.025,typ*1.75))
    if adverse>=hard:return "hard_catastrophe_stop"
    return None


def _pnl(pos,exit_price):
    move=pos["side"]*(exit_price/pos["entry"]-1.0)
    return pos["notional"]*(move-2*FEE)


def _unrealized(pos,mark):
    return _pnl(pos,mark)


def _entry_not_chased(anchor,m15,mark):
    ref=float(anchor.get("confirmation_close") or anchor.get("pivot_price") or 0)
    if ref<=0:return False
    typical=float(m15.get("median_range_move") or .008)
    limit=max(.004,min(.020,typical*2))
    return abs(mark/ref-1)<=limit


def run_backtest(start_date=None,days=7):
    today=dt.datetime.now(dt.timezone.utc).date()
    end_date=today
    if start_date:
        start=dt.date.fromisoformat(str(start_date))
        end_date=start+dt.timedelta(days=int(days))
    else:
        start=end_date-dt.timedelta(days=int(days))
    warm=start-dt.timedelta(days=1)
    start_epoch=dt.datetime.combine(start,dt.time(0),tzinfo=dt.timezone.utc).timestamp()
    end_epoch=dt.datetime.combine(end_date,dt.time(0),tzinfo=dt.timezone.utc).timestamp()
    warm_epoch=dt.datetime.combine(warm,dt.time(0),tzinfo=dt.timezone.utc).timestamp()

    data={};coverage={}
    days_list=[];d=warm
    while d<end_date:
        days_list.append(d);d+=dt.timedelta(days=1)

    def load_one(symbol,d):
        try:
            spool,nbytes,url=_download_day(symbol,d)
            try:
                part,n=_parse_day(spool,warm_epoch,end_epoch)
            finally:
                spool.close()
            return symbol,d,part,n,nbytes,url,None
        except Exception as exc:
            return symbol,d,{},0,0,None,type(exc).__name__+":"+str(exc)[:100]

    # Load all symbol/day archives concurrently instead of serializing symbols.
    # This is research-only and does not mutate the live PAPER state.
    max_workers=max(4,min(32,int(os.getenv("S1_ARCHIVE_WORKERS","16"))))
    grouped={s:[] for s in SYMBOLS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix="bybit-archive") as pool:
        futures=[pool.submit(load_one,symbol,d) for symbol in SYMBOLS for d in days_list]
        for future in concurrent.futures.as_completed(futures):
            symbol,d,part,n,nbytes,url,err=future.result()
            grouped[symbol].append((d,part,n,nbytes,url,err))

    for symbol in SYMBOLS:
        buckets={};files=[];trades=0
        for d,part,n,nbytes,url,err in sorted(grouped[symbol],key=lambda x:x[0]):
            if err:
                files.append({"date":d.isoformat(),"ok":False,"error":err})
                print("S1_WEEK_ARCHIVE_ERROR",json.dumps({"symbol":symbol,"date":d.isoformat(),"error":err},separators=(",",":")),flush=True)
                continue
            _merge_buckets(buckets,part);trades+=n
            files.append({"date":d.isoformat(),"url":url,"ok":True,"bytes":nbytes,"trades":n})
            print("S1_WEEK_ARCHIVE",json.dumps({"symbol":symbol,"date":d.isoformat(),"bytes":nbytes,"trades":n},separators=(",",":")),flush=True)
        data[symbol]={"buckets":buckets,"m15":_bars(buckets,900),"h1":_bars(buckets,3600),
                      "events":_h1_events(_bars(buckets,3600))}
        coverage[symbol]={"files":files,"trade_rows":trades,"bucket15s":len(buckets),
                          "archive_workers":max_workers}

    missing={s:[x["date"] for x in coverage[s]["files"] if not x.get("ok")] for s in SYMBOLS}
    if any(len(v)>1 for v in missing.values()):
        raise RuntimeError("insufficient_archive_coverage:"+json.dumps(missing,sort_keys=True))

    cash=500.0;positions={};watches={};anchors={};event_idx={s:0 for s in SYMBOLS}
    last_price={};trades=[];equity_curve=[];per={s:{"pnl":0.0,"trades":0,"wins":0} for s in SYMBOLS}
    all_times=sorted(set(t for s in SYMBOLS for t in data[s]["buckets"] if start_epoch<=t<end_epoch))
    max_equity=500.0;min_equity=500.0;peak=500.0;max_dd=0.0

    for t in all_times:
        for s in SYMBOLS:
            b=data[s]["buckets"].get(t)
            if b:last_price[s]=b["c"]
            evs=data[s]["events"];i=event_idx[s]
            while i<len(evs) and evs[i]["at"]<=t:
                anchors[s]=evs[i];i+=1
            event_idx[s]=i

        def mtm():
            return cash+sum(_unrealized(p,last_price.get(s,p["entry"])) for s,p in positions.items())
        equity=mtm()
        used=sum(p["margin"] for p in positions.values())
        free=equity-used

        for s in SYMBOLS:
            mark=last_price.get(s);anchor=anchors.get(s)
            if mark is None or anchor is None:continue
            pos=positions.get(s);watch=watches.get(s)
            side=(pos or watch or {}).get("side") or anchor.get("entry_side")
            if side not in (-1,1):continue
            m15=_m15_at(data[s]["buckets"],data[s]["m15"],t,int(side))
            flow=_flow(data[s]["buckets"],t,int(side))
            if not m15.get("ready"):continue

            if pos:
                move=pos["side"]*(mark/pos["entry"]-1)
                f=pos.setdefault("features",{})
                f["mfe_price_move"]=max(float(f.get("mfe_price_move",0) or 0),move)
                f["mae_price_move"]=min(float(f.get("mae_price_move",0) or 0),move)
                reason=None
                if int(anchor.get("entry_side") or 0)==-int(pos["side"]):
                    reason="opposite_confirmed_h1_local"
                else:
                    reason=pressure_exit(pos,m15,mark,flow) or _stop(pos,m15,mark,flow)
                if reason:
                    pnl=_pnl(pos,mark);cash+=pnl
                    trades.append({"opened_t":pos.get("opened"),"closed_t":t,"symbol":s,"side":pos["side"],
                                   "entry":pos["entry"],"exit":mark,"margin":pos["margin"],"notional":pos["notional"],
                                   "leverage":pos["leverage"],"pnl":pnl,"reason":reason,"equity_after":cash,
                                   "mfe_price_move":float(f.get("mfe_price_move",0) or 0),
                                   "mae_price_move":float(f.get("mae_price_move",0) or 0)})
                    per[s]["pnl"]+=pnl;per[s]["trades"]+=1;per[s]["wins"]+=int(pnl>0)
                    watches[s]={"symbol":s,"side":pos["side"],"origin_signal_candle":pos.get("signal_candle_time",0),
                                "exit_price":mark,"exit_at":dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat(),
                                "reentries":int(f.get("swing_reentries",0) or 0),
                                "context":{"phase":"WAIT_PULLBACK","counter_pressure_seen":False,
                                           "pullback_extreme":mark,"anchor":dict(f)}}
                    del positions[s]
                continue

            if watch:
                if int(anchor.get("entry_side") or 0)==-int(watch["side"]):
                    watches.pop(s,None);watch=None
                else:
                    watch=update_watch(watch,mark,m15,flow,t+15)
                    watches[s]=watch
                if watch and reentry_ready(int(watch["side"]),m15,mark,watch,flow,t+15):
                    equity=mtm();used=sum(p["margin"] for p in positions.values());free=equity-used
                    margin=max(.01,equity*MARGIN_FRACTION)
                    if free+1e-9>=margin:
                        positions[s]={"symbol":s,"side":int(watch["side"]),"entry":mark,"margin":margin,
                                      "notional":margin*LEV,"leverage":LEV,"opened":t,
                                      "signal_candle_time":anchor.get("signal_candle_time",0),
                                      "features":{"estimated_round_trip_cost_move":2*FEE+.0004,
                                                  "entry_kind":"REENTRY","mfe_price_move":0.0,"mae_price_move":0.0}}
                        watches.pop(s,None)
                continue

            candidate=entry_candidate(s,anchor,m15,flow,t+15)
            if candidate.get("eligible") and _entry_not_chased(anchor,m15,mark):
                equity=mtm();used=sum(p["margin"] for p in positions.values());free=equity-used
                margin=max(.01,equity*MARGIN_FRACTION)
                if free+1e-9>=margin:
                    positions[s]={"symbol":s,"side":int(anchor["entry_side"]),"entry":mark,"margin":margin,
                                  "notional":margin*LEV,"leverage":LEV,"opened":t,
                                  "signal_candle_time":anchor.get("signal_candle_time",0),
                                  "features":{"estimated_round_trip_cost_move":2*FEE+.0004,
                                              "entry_kind":"FIRST","mfe_price_move":0.0,"mae_price_move":0.0}}

        equity=mtm();peak=max(peak,equity);max_equity=max(max_equity,equity);min_equity=min(min_equity,equity)
        if peak>0:max_dd=max(max_dd,(peak-equity)/peak)
        if not equity_curve or t-equity_curve[-1][0]>=300:equity_curve.append((t,equity))

    final_equity=cash+sum(_unrealized(p,last_price.get(s,p["entry"])) for s,p in positions.items())
    closed_pnl=sum(x["pnl"] for x in trades)
    wins=sum(1 for x in trades if x["pnl"]>0)
    losses=[-x["pnl"] for x in trades if x["pnl"]<0];gains=[x["pnl"] for x in trades if x["pnl"]>0]
    pf=(sum(gains)/sum(losses)) if losses else (float("inf") if gains else None)
    for s in SYMBOLS:
        per[s]["win_rate"]=per[s]["wins"]/per[s]["trades"] if per[s]["trades"] else None
    history_rows=[]
    for x in trades:
        y=dict(x)
        y["opened"]=dt.datetime.fromtimestamp(float(x["opened_t"]),dt.timezone.utc).isoformat() if x.get("opened_t") else None
        y["closed"]=dt.datetime.fromtimestamp(float(x["closed_t"]),dt.timezone.utc).isoformat() if x.get("closed_t") else None
        history_rows.append(y)
    return {"research_only":True,"causal":True,"source":"official_bybit_public_trade_archives",
            "start":start.isoformat(),"end_exclusive":end_date.isoformat(),"starting_equity":500.0,
            "final_equity":final_equity,"return_pct":(final_equity/500-1)*100,
            "realized_pnl":closed_pnl,"open_pnl":final_equity-cash,
            "cash_equity":cash,"max_equity":max_equity,"min_equity":min_equity,
            "max_drawdown_pct":max_dd*100,"closed_trades":len(trades),
            "wins":wins,"win_rate":wins/len(trades) if trades else None,"profit_factor":pf,
            "per_symbol":per,"open_positions":positions,"coverage":coverage,
            "trades":history_rows[-500:],"policy":"h1_multihorizon_flow_caterpillar_v14_universal_25x"}


def _worker(start_date,days):
    with LOCK:
        STATE.update(status="running",started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                     finished_at=None,result=None,error=None)
    try:
        result=run_backtest(start_date,days)
        summary={k:result.get(k) for k in ("start","end_exclusive","starting_equity","final_equity","return_pct","realized_pnl","open_pnl","max_drawdown_pct","closed_trades","wins","win_rate","profit_factor")}
        summary["per_symbol"]=result.get("per_symbol")
        print("S1_WEEK_BACKTEST_RESULT",json.dumps(summary,default=str,separators=(",",":")),flush=True)
        with LOCK:STATE.update(status="done",finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),result=result)
    except Exception as exc:
        err=type(exc).__name__+":"+str(exc)
        print("S1_WEEK_BACKTEST_ERROR",err,flush=True)
        with LOCK:STATE.update(status="error",finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                               error=err)


def start(start_date=None,days=7):
    with LOCK:
        if STATE.get("status")=="running":return dict(STATE)
        th=threading.Thread(target=_worker,args=(start_date,days),name="s1-week-backtest",daemon=True)
        th.start()
        return {"status":"starting","start_date":start_date,"days":days}


def status():
    with LOCK:return json.loads(json.dumps(STATE,default=str))
