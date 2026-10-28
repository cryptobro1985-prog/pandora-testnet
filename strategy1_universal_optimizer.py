"""Universal Strategy 1 parameter optimizer.

Research-only. Uses official Bybit public trade archives and searches one shared
parameter set for entry, weakening exit, pullback/re-entry and volatility stops.
Selection is robustness-first: walk-forward validation + cross-symbol stability,
not maximum in-sample ending equity.
"""
import datetime as dt
import itertools
import json
import math
import statistics
import threading
import time

import strategy1_week_backtest as bt

STATE={"status":"idle","started_at":None,"finished_at":None,"result":None,"error":None}
LOCK=threading.RLock()

BASE={
 "entry15":.16,"entry30":.12,"entry60":.08,"entry_recovery":3,"entry_adverse_max":1,
 "weak15":.02,"weak30":.06,"weak_drop":.08,"exit_recoil_mult":.15,
 "counter15":-.12,"counter30":-.08,
 "pullback_mult":.15,"rebound_mult":.10,
 "reentry15":.20,"reentry30":.15,"reentry60":.10,"reentry_recovery":3,
 "soft_mult":1.35,"soft_floor":.0075,"soft_cap":.018,
 "hard_mult":1.75,"hard_floor":.015,"hard_cap":.025,
 "chase_mult":2.0,
}
SYMBOLS=bt.SYMBOLS
FEE=bt.FEE
LEV=bt.LEV
MF=bt.MARGIN_FRACTION


def _threshold(m15,mult,floor=.0006,cap=.0018):
    return max(floor,min(cap,float(m15.get("median_range_move") or .008)*mult))


def _aligned(flow,side,key):
    return side*float(flow.get(key) or 0.0)


def _entry_ok(anchor,m15,flow,mark,p):
    side=int(anchor.get("entry_side") or 0)
    if side not in (-1,1) or not m15.get("ready") or int(m15.get("side") or 0)!=side:return False
    if not flow.get("trade_data_fresh") or int(flow.get("trade_count_60s") or 0)<5 or float(flow.get("observed_notional_60s") or 0)<100:return False
    if int(m15.get("recovery_score") or 0)<p["entry_recovery"] or int(m15.get("adverse_score") or 0)>p["entry_adverse_max"]:return False
    if not m15.get("recovery_confirmed"):return False
    if _aligned(flow,side,"flow_imbalance_15s")<p["entry15"]:return False
    if _aligned(flow,side,"flow_imbalance_30s")<p["entry30"]:return False
    if _aligned(flow,side,"flow_imbalance")<p["entry60"]:return False
    ref=float(anchor.get("confirmation_close") or anchor.get("pivot_price") or 0)
    if ref<=0:return False
    lim=max(.004,min(.025,float(m15.get("median_range_move") or .008)*p["chase_mult"]))
    return abs(mark/ref-1)<=lim


def _exit_reason(pos,m15,flow,mark,p):
    side=pos["side"];entry=pos["entry"]
    move=side*(mark/entry-1)
    peak=max(float(pos.get("mfe",0) or 0),move,0)
    recoil=peak-move
    typical=max(.0005,float(m15.get("median_range_move") or .008))
    a15=_aligned(flow,side,"flow_imbalance_15s")
    a30=_aligned(flow,side,"flow_imbalance_30s")
    a60=_aligned(flow,side,"flow_imbalance")
    candle=(int(m15.get("candle_direction") or 0)==-side and float(m15.get("body_fraction") or 0)>=.42)
    price_confirm=candle or side*float(m15.get("return_15m") or 0)<0 or int(m15.get("adverse_score") or 0)>=2
    weakening=(a15<p["weak15"] and a30<p["weak30"] and a15<=a60-p["weak_drop"])
    counter=(a15<=p["counter15"] and a30<=p["counter30"])
    if recoil>=_threshold(m15,p["exit_recoil_mult"]) and move>2*FEE+.0004 and weakening and price_confirm:
        return "weakening"
    if counter and (int(m15.get("adverse_score") or 0)>=3 or candle):
        return "counter_control"
    adverse=max(0.0,-side*(mark/entry-1))
    soft=max(p["soft_floor"],min(p["soft_cap"],typical*p["soft_mult"]))
    strong=bool(m15.get("strong_adverse_pressure")) and int(m15.get("adverse_score") or 0)>=3
    if adverse>=soft and candle and (counter or strong):return "soft_stop"
    hard=max(p["hard_floor"],min(p["hard_cap"],typical*p["hard_mult"]))
    if adverse>=hard:return "hard_stop"
    return None


def _watch_update(watch,mark,m15,flow,t,p):
    side=watch["side"];exitp=watch["exit_price"]
    extreme=watch.get("extreme",exitp)
    extreme=min(extreme,mark) if side>0 else max(extreme,mark)
    watch["extreme"]=extreme
    pull=max(0.0,-side*(extreme/exitp-1))
    a15=_aligned(flow,side,"flow_imbalance_15s");a30=_aligned(flow,side,"flow_imbalance_30s")
    if a15<-.08 and a30<-.05:watch["counter_seen"]=True
    if watch.get("phase")=="WAIT_PULLBACK" and watch.get("counter_seen") and pull>=_threshold(m15,p["pullback_mult"]):
        watch["phase"]="WAIT_RESUMPTION";watch["confirmed_t"]=t
    return watch


def _reentry_ok(watch,m15,flow,mark,t,p):
    side=watch["side"]
    if watch.get("phase")!="WAIT_RESUMPTION" or not watch.get("counter_seen"):return False
    if t<=watch.get("confirmed_t",t):return False
    if not m15.get("ready") or int(m15.get("recovery_score") or 0)<p["reentry_recovery"] or int(m15.get("adverse_score") or 0)>1:return False
    if not m15.get("recovery_confirmed"):return False
    if _aligned(flow,side,"flow_imbalance_15s")<p["reentry15"]:return False
    if _aligned(flow,side,"flow_imbalance_30s")<p["reentry30"]:return False
    if _aligned(flow,side,"flow_imbalance")<p["reentry60"]:return False
    rebound=side*(mark/watch["extreme"]-1)
    if rebound<_threshold(m15,p["rebound_mult"]):return False
    loc=m15.get("close_location")
    if loc is not None and ((side>0 and loc<.60) or (side<0 and loc>.40)):return False
    return True


def _pnl(pos,price):
    return pos["notional"]*(pos["side"]*(price/pos["entry"]-1)-2*FEE)


def _simulate(data,start_epoch,end_epoch,p,symbols=SYMBOLS,start_equity=500.0):
    cash=float(start_equity);positions={};watches={};anchors={};idx={s:0 for s in symbols};last={}
    trades=[];peak=cash;maxdd=0.0;min_eq=cash
    times=sorted(set(t for s in symbols for t in data[s]["buckets"] if start_epoch<=t<end_epoch))
    # Seed anchor from all H1 events known at the fold start.
    for s in symbols:
        evs=data[s]["events"];i=0
        while i<len(evs) and evs[i]["at"]<=start_epoch:anchors[s]=evs[i];i+=1
        idx[s]=i
    for t in times:
        for s in symbols:
            b=data[s]["buckets"].get(t)
            if b:last[s]=b["c"]
            evs=data[s]["events"];i=idx[s]
            while i<len(evs) and evs[i]["at"]<=t:anchors[s]=evs[i];i+=1
            idx[s]=i
        def eq():
            return cash+sum(_pnl(pos,last.get(s,pos["entry"])) for s,pos in positions.items())
        for s in symbols:
            mark=last.get(s);a=anchors.get(s)
            if mark is None or not a:continue
            pos=positions.get(s);watch=watches.get(s)
            side=(pos or watch or {}).get("side") or a.get("entry_side")
            if side not in (-1,1):continue
            m15=bt._m15_at(data[s]["buckets"],data[s]["m15"],t,int(side))
            if not m15.get("ready"):continue
            flow=bt._flow(data[s]["buckets"],t,int(side))
            if pos:
                move=pos["side"]*(mark/pos["entry"]-1);pos["mfe"]=max(pos.get("mfe",0),move)
                reason="h1_flip" if int(a.get("entry_side") or 0)==-pos["side"] else _exit_reason(pos,m15,flow,mark,p)
                if reason:
                    v=_pnl(pos,mark);cash+=v;trades.append((s,v,reason))
                    watches[s]={"side":pos["side"],"exit_price":mark,"extreme":mark,"phase":"WAIT_PULLBACK","counter_seen":False,"confirmed_t":None}
                    del positions[s]
                continue
            if watch:
                if int(a.get("entry_side") or 0)==-watch["side"]:
                    watches.pop(s,None);watch=None
                else:
                    watch=_watch_update(watch,mark,m15,flow,t,p);watches[s]=watch
                if watch and _reentry_ok(watch,m15,flow,mark,t,p):
                    equity=eq();used=sum(x["margin"] for x in positions.values());margin=max(.01,equity*MF)
                    if equity-used+1e-9>=margin:
                        positions[s]={"side":watch["side"],"entry":mark,"margin":margin,"notional":margin*LEV,"mfe":0.0}
                        watches.pop(s,None)
                continue
            if _entry_ok(a,m15,flow,mark,p):
                equity=eq();used=sum(x["margin"] for x in positions.values());margin=max(.01,equity*MF)
                if equity-used+1e-9>=margin:
                    positions[s]={"side":int(a["entry_side"]),"entry":mark,"margin":margin,"notional":margin*LEV,"mfe":0.0}
        equity=eq();peak=max(peak,equity);min_eq=min(min_eq,equity)
        if peak>0:maxdd=max(maxdd,(peak-equity)/peak)
        if equity<=0:return {"final_equity":equity,"return_pct":-100.0,"max_dd_pct":100.0,"trades":len(trades),"wins":0,"pf":0.0}
    final=eq();wins=sum(v>0 for _,v,_ in trades);g=sum(v for _,v,_ in trades if v>0);l=-sum(v for _,v,_ in trades if v<0)
    return {"final_equity":final,"return_pct":(final/start_equity-1)*100,"max_dd_pct":maxdd*100,
            "trades":len(trades),"wins":wins,"win_rate":wins/len(trades) if trades else 0.0,
            "pf":g/l if l>0 else (99.0 if g>0 else 0.0),"min_equity":min_eq}


def _candidate_params():
    # Deterministic coarse neighborhood around the live v14 values.
    entry_sets=[
      (.12,.08,.04,2),(.14,.10,.06,3),(.16,.12,.08,3),(.18,.14,.10,3),(.20,.15,.10,4)
    ]
    exit_sets=[
      (.00,.04,.06,.10),(.02,.06,.08,.15),(.04,.08,.10,.15),(.06,.10,.12,.20)
    ]
    re_sets=[
      (.15,.10,.06,2,.10,.08),(.18,.12,.08,3,.15,.10),(.20,.15,.10,3,.15,.10),(.24,.18,.12,4,.20,.12)
    ]
    stop_sets=[
      (1.0,.006,.015,1.5,.012,.020),(1.35,.0075,.018,1.75,.015,.025),
      (1.6,.008,.020,2.0,.018,.028),(1.8,.010,.022,2.2,.020,.030)
    ]
    out=[]
    for e,x,r,s in itertools.product(entry_sets,exit_sets,re_sets,stop_sets):
        p=dict(BASE)
        p.update(entry15=e[0],entry30=e[1],entry60=e[2],entry_recovery=e[3])
        p.update(weak15=x[0],weak30=x[1],weak_drop=x[2],exit_recoil_mult=x[3])
        p.update(reentry15=r[0],reentry30=r[1],reentry60=r[2],reentry_recovery=r[3],
                 pullback_mult=r[4],rebound_mult=r[5])
        p.update(soft_mult=s[0],soft_floor=s[1],soft_cap=s[2],hard_mult=s[3],hard_floor=s[4],hard_cap=s[5])
        out.append(p)
    return out


def _load_data(days=7):
    today=dt.datetime.now(dt.timezone.utc).date();end=today;start=end-dt.timedelta(days=days);warm=start-dt.timedelta(days=1)
    se=dt.datetime.combine(start,dt.time(0),tzinfo=dt.timezone.utc).timestamp()
    ee=dt.datetime.combine(end,dt.time(0),tzinfo=dt.timezone.utc).timestamp()
    we=dt.datetime.combine(warm,dt.time(0),tzinfo=dt.timezone.utc).timestamp()
    data={};coverage={}
    for symbol in SYMBOLS:
        buckets={};rows=0;files=[];d=warm
        while d<end:
            try:
                spool,nbytes,url=bt._download_day(symbol,d)
                try:part,n=bt._parse_day(spool,we,ee)
                finally:spool.close()
                bt._merge_buckets(buckets,part);rows+=n;files.append((d.isoformat(),n,nbytes))
                print("S1_OPT_ARCHIVE",json.dumps({"symbol":symbol,"date":d.isoformat(),"trades":n,"bytes":nbytes},separators=(",",":")),flush=True)
            except Exception as exc:
                print("S1_OPT_ARCHIVE_ERROR",symbol,d.isoformat(),type(exc).__name__,str(exc)[:100],flush=True)
            d+=dt.timedelta(days=1)
        m15=bt._bars(buckets,900);h1=bt._bars(buckets,3600)
        data[symbol]={"buckets":buckets,"m15":m15,"h1":h1,"events":bt._h1_events(h1)}
        coverage[symbol]={"trades":rows,"bucket15s":len(buckets),"files":files}
    return data,start,end,se,ee,coverage


def optimize(days=7):
    data,start,end,se,ee,coverage=_load_data(days)
    # Walk-forward folds: first 4 days train, last 3 validation, plus per-symbol OOS.
    split=se+4*86400
    candidates=_candidate_params()
    ranked=[]
    for i,p in enumerate(candidates):
        train=_simulate(data,se,split,p)
        valid=_simulate(data,split,ee,p)
        per={}
        token_scores=[]
        for s in SYMBOLS:
            r=_simulate(data,split,ee,p,(s,))
            per[s]=r
            token_scores.append(r["return_pct"])
        # Robust objective rewards OOS return but heavily punishes drawdown and one-token dependence.
        med=statistics.median(token_scores)
        worst=min(token_scores)
        dispersion=statistics.pstdev(token_scores) if len(token_scores)>1 else 0
        score=(valid["return_pct"] + .35*med + .15*worst
               - .75*valid["max_dd_pct"] - .10*dispersion)
        if valid["trades"]<4:score-=50
        if train["final_equity"]<=0 or valid["final_equity"]<=0:score-=1000
        ranked.append({"score":score,"params":p,"train":train,"validation":valid,"validation_by_symbol":per})
        if i%40==0:
            print("S1_OPT_PROGRESS",json.dumps({"done":i+1,"total":len(candidates),"best":max(x["score"] for x in ranked)},separators=(",",":")),flush=True)
    ranked.sort(key=lambda x:x["score"],reverse=True)
    top=ranked[:12]
    best=top[0]
    result={"research_only":True,"method":"walk_forward_cross_symbol_robust_grid",
            "start":start.isoformat(),"end_exclusive":end.isoformat(),"candidates":len(candidates),
            "coverage":coverage,"best":best,"top12":top,
            "selection_note":"Chosen by OOS return, cross-symbol median/worst return and drawdown penalty; not by maximum in-sample equity."}
    print("S1_OPT_RESULT",json.dumps({"candidates":len(candidates),"best_score":best["score"],"best_params":best["params"],
          "train":best["train"],"validation":best["validation"],
          "validation_by_symbol":best["validation_by_symbol"]},default=str,separators=(",",":")),flush=True)
    return result


def _worker(days):
    with LOCK:STATE.update(status="running",started_at=dt.datetime.now(dt.timezone.utc).isoformat(),finished_at=None,result=None,error=None)
    try:
        r=optimize(days)
        with LOCK:STATE.update(status="done",finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),result=r)
    except Exception as exc:
        err=type(exc).__name__+":"+str(exc)
        print("S1_OPT_ERROR",err,flush=True)
        with LOCK:STATE.update(status="error",finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),error=err)


def start(days=7):
    with LOCK:
        if STATE.get("status")=="running":return {"status":"running"}
        threading.Thread(target=_worker,args=(days,),daemon=True,name="s1-universal-optimizer").start()
        return {"status":"starting","days":days}


def status():
    with LOCK:return json.loads(json.dumps(STATE,default=str))
