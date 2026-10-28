"""Fixed-logic 12h causal comparison: v14 flow baseline vs algo-footprint enhancement."""
import datetime as dt
import json
import threading
import strategy1_universal_optimizer as opt

STATE={"status":"idle","result":None,"error":None}
LOCK=threading.RLock()

ALGO=dict(opt.BASE)
ALGO.update({
 "algo_entry_persistence":.10,"algo_entry_intensity":0.0,
 "algo_reentry_persistence":.12,"algo_reentry_intensity":0.0,
 "algo_peer_min":-.10,"algo_exit_enabled":True,
})
BASELINE=dict(opt.BASE)
BASELINE.update({
 "algo_entry_persistence":-.20,"algo_entry_intensity":-1.0,
 "algo_reentry_persistence":-.20,"algo_reentry_intensity":-1.0,
 "algo_peer_min":-1.0,"algo_exit_enabled":False,
})

def _mfe_upper(data,start,end,start_equity=500.0):
    # Informational hindsight ceiling only: never used for decisions.
    # For each H1-side segment and symbol, mark best favorable excursion, applying
    # 20% equity x25 reference exposure sequentially by segment close time.
    rows=[]
    for s in opt.SYMBOLS:
        events=[e for e in data[s]["events"] if e["at"]<end]
        buckets=data[s]["buckets"]
        for i,e in enumerate(events):
            seg_start=max(start,e["at"])
            seg_end=min(end,events[i+1]["at"] if i+1<len(events) else end)
            if seg_end<=seg_start:continue
            pts=[b for t,b in buckets.items() if seg_start<=t<seg_end]
            if not pts:continue
            pts=sorted(pts,key=lambda x:x["t"])
            entry=pts[0]["o"];side=int(e["entry_side"])
            best=max((side*(b["c"]/entry-1),b["t"],b["c"]) for b in pts)
            rows.append({"symbol":s,"start":seg_start,"end":seg_end,"side":side,
                         "entry":entry,"best_move":best[0],"best_t":best[1],"best_price":best[2]})
    rows.sort(key=lambda x:x["best_t"])
    equity=start_equity
    for r in rows:
        if r["best_move"]>0:
            notional=equity*opt.MF*opt.LEV
            pnl=notional*(r["best_move"]-2*opt.FEE)
            if pnl>0:equity+=pnl
    return {"hindsight_upper_equity":equity,"segments":len(rows)}

def run():
    data,start_date,end_date,se,ee,coverage=opt._load_data(2)
    # Prefer the latest 12h ending at the dataset's last common 15s bucket.
    last_common=min(max(data[s]["buckets"]) for s in opt.SYMBOLS if data[s]["buckets"])
    end=min(ee,last_common+15)
    start=end-12*3600
    observations=opt._precompute(data,start,end)
    # Single-symbol diagnostics and shared-compound portfolio.
    per_base={s:opt._simulate_series(observations[s],start,end,BASELINE) for s in opt.SYMBOLS}
    per_algo={s:opt._simulate_series(observations[s],start,end,ALGO) for s in opt.SYMBOLS}
    portfolio_base=opt._simulate(data,start,end,BASELINE)
    portfolio_algo=opt._simulate(data,start,end,ALGO)
    ceiling=_mfe_upper(data,start,end)
    capture_base=(portfolio_base["final_equity"]-500)/(ceiling["hindsight_upper_equity"]-500) if ceiling["hindsight_upper_equity"]>500 else None
    capture_algo=(portfolio_algo["final_equity"]-500)/(ceiling["hindsight_upper_equity"]-500) if ceiling["hindsight_upper_equity"]>500 else None
    result={
      "research_only":True,"causal":True,"fixed_before_test":True,
      "window_start_utc":dt.datetime.fromtimestamp(start,dt.timezone.utc).isoformat(),
      "window_end_utc":dt.datetime.fromtimestamp(end,dt.timezone.utc).isoformat(),
      "starting_equity":500.0,"margin_fraction":opt.MF,"leverage":opt.LEV,
      "baseline":portfolio_base,"algo":portfolio_algo,
      "per_symbol_baseline":per_base,"per_symbol_algo":per_algo,
      "hindsight_ceiling":ceiling,
      "capture_ratio_baseline":capture_base,"capture_ratio_algo":capture_algo,
      "algo_params":ALGO,"coverage":coverage
    }
    print("S1_ALGO_12H_RESULT",json.dumps(result,default=str,separators=(",",":")),flush=True)
    return result

def _worker():
    with LOCK:STATE.update(status="running",result=None,error=None)
    try:
        r=run()
        with LOCK:STATE.update(status="done",result=r)
    except Exception as exc:
        err=type(exc).__name__+":"+str(exc)
        print("S1_ALGO_12H_ERROR",err,flush=True)
        with LOCK:STATE.update(status="error",error=err)

def start():
    with LOCK:
        if STATE["status"]=="running":return {"status":"running"}
        threading.Thread(target=_worker,daemon=True,name="s1-algo-12h").start()
        return {"status":"starting"}

def status():
    with LOCK:return json.loads(json.dumps(STATE,default=str))
