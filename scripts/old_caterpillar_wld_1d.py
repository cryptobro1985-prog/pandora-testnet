from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse, json, math, csv, gzip
from concurrent.futures import ThreadPoolExecutor

from research.caterpillar.caterpillar.sources import Archives, archive_row
from market_data import RollingMarketData
from scripts.historical_224d_hype_h1_swing import analyze, analyze_m15, position_exit, update_path
from scripts.historical_224d_local_caterpillar import update_watch

SYMBOL="WLD"; START=500.0; MARGIN=.20; LEV=25.0; FEE=.00045
DECISION_CADENCE=5.0
S1_PYRAMID_MARGIN_FRACTION=.05
S1_PYRAMID_MIN_ROE_PCT=20.0
S1_PYRAMID_COOLDOWN_SECONDS=60.0

def paper_pnl(n,e,x,s):
    out=n*(x/e)
    return (out-n)*s-FEE*(n+out)

def bucket_update(d,x,seconds):
    k=int(x.ts//seconds)*seconds
    b=d.get(k)
    if b is None:
        b=d[k]={"t":k*1000,"T":(k+seconds)*1000-1,"o":x.price,"h":x.price,"l":x.price,"c":x.price,"v":x.quantity}
    else:
        b["h"]=max(b["h"],x.price); b["l"]=min(b["l"],x.price); b["c"]=x.price; b["v"]+=x.quantity

def rows(d, keep=160):
    return [d[k] for k in sorted(d)[-keep:]]

def fresh_h1_trigger(a, now_epoch, max_age=120.0):
    if not a or not a.get("anchor_confirmed"): return False
    close_ms=float(a.get("signal_candle_close_time") or 0)
    if close_ms<=0: return False
    age=now_epoch-close_ms/1000.0
    return -2.0<=age<=max_age

def weakening_exit(pos,m15,mark,flow):
    if not pos or not flow.get("trade_data_fresh"): return False
    side=int(pos["side"]); entry=float(pos["entry"])
    if float(flow.get("trade_coverage_seconds") or 0)<180: return False
    try:
        i60=side*float(flow["flow_imbalance"]); i180=side*float(flow["flow_imbalance_180s"])
        c60=float(flow.get("trade_count_60s") or 0); c180=float(flow.get("trade_count_180s") or 0)
    except (TypeError,ValueError,KeyError): return False
    if c60<5 or c180<12 or i60>-.18 or i180>-.08: return False
    favorable=side*(mark/entry-1.0)
    peak=max(0.0,float(pos.get("features",{}).get("mfe_price_move") or 0),favorable)
    typical=float((m15 or {}).get("median_range_move") or .008)
    recoil=max(.0007,min(.0018,typical*.12))
    return peak-favorable>=recoil

def reentry_ready(side,m15,mark,watch,flow):
    # Exact helper from app.py @ 224dff69. The phase name is intentionally
    # preserved byte-for-byte semantically; no repair is made in this replay.
    if side not in (-1,1) or not m15 or not m15.get("ready") or not watch: return False
    ctx=watch.get("context") or {}
    if ctx.get("phase")!="WAIT_RESUMPTION" or not ctx.get("counter_pressure_seen"): return False
    if not flow.get("trade_data_fresh"): return False
    try: imb=float(flow.get("flow_imbalance"))
    except (TypeError,ValueError): return False
    if side*imb<.12: return False
    coverage=float(flow.get("trade_coverage_seconds") or 0)
    i180=flow.get("flow_imbalance_180s"); i300=flow.get("flow_imbalance_300s")
    if coverage<300 or i180 is None or i300 is None: return False
    if side*imb<.12 or side*float(i180)<.08 or side*float(i300)<.08: return False
    if int(m15.get("recovery_score") or 0)<2 or int(m15.get("adverse_score") or 0)>1: return False
    extreme=float(ctx.get("pullback_extreme") or watch.get("exit_price") or 0)
    if extreme<=0 or mark<=0: return False
    typical=float(m15.get("median_range_move") or .008)
    resume=max(.0005,min(.0012,typical*.10))
    return side*(mark/extreme-1.0)>=resume

def mtm(cash,pos,mark):
    return cash+(paper_pnl(pos["notional"],pos["entry"],mark,pos["side"]) if pos else 0.0)

def close_trade(cash,pos,mark,ts,reason,trades,arm_watch=False,watch_phase="WAIT_PULLBACK"):
    pnl=paper_pnl(pos["notional"],pos["entry"],mark,pos["side"]); cash+=pnl
    best=pos.get("best_mark",pos["entry"]); mfe=paper_pnl(pos["notional"],pos["entry"],best,pos["side"])
    trades.append({**pos,"exit":mark,"closed":ts,"pnl":pnl,"reason":reason,"mfe_net_pnl":mfe,"giveback_vs_mfe":mfe-pnl})
    watch=None
    if arm_watch:
        watch={"symbol":SYMBOL,"side":int(pos["side"]),"origin_signal_candle":int(pos.get("signal_candle_time") or 0),
               "exit_price":mark,"exit_at":ts,"reentries":int(pos.get("features",{}).get("swing_reentries",0) or 0),
               "context":{"phase":watch_phase,"counter_pressure_seen":False,"pullback_extreme":mark,"anchor":dict(pos.get("features") or {})}}
    return cash,watch

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--cache",type=Path,required=True); ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    src=Archives(a.cache); day=datetime(2026,11,2,tzinfo=timezone.utc); end=day+timedelta(days=1)

    # Pre-download the six official Bybit trade archives concurrently, then
    # parse each exactly once. This preserves archive-derived candles while
    # avoiding the source helper's extra full validation pass.
    days=[day-timedelta(days=i) for i in range(5, -1, -1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        got=list(pool.map(lambda d: src.obtain(SYMBOL,d),days))
    paths={d:p for d,(p,m) in zip(days,got)}; metas=[m for p,m in got]
    def file_trades(d):
        with gzip.open(paths[d],"rt",newline="") as handle:
            for line,row in enumerate(csv.DictReader(handle),2):
                yield archive_row(SYMBOL,row,line)
    h1d={}; m15d={}
    for d in days[:-1]:
        for x in file_trades(d):
            bucket_update(h1d,x,3600)
            if d>=day-timedelta(days=1): bucket_update(m15d,x,900)

    # Exact RollingMarketData 5-second bucket semantics, warmed only by the
    # final 10 minutes before midnight, with exchange time == receipt time.
    obs=RollingMarketData(bucket_seconds=5,retention_seconds=600,max_symbols=8,max_trade_lag_seconds=360,freshness_seconds=15)
    warm_start=day.timestamp()-600
    obs.mark_connected(warm_start,[SYMBOL])
    wit=file_trades(day-timedelta(days=1))
    tid=0
    for x in wit:
        if x.ts<warm_start: continue
        if x.ts>=day.timestamp(): break
        tid+=1
        obs.heartbeat(x.ts)
        obs.ingest_trades([{"coin":SYMBOL,"px":x.price,"sz":x.quantity,"time":x.ts*1000,"tid":"w"+str(tid),"side":"B" if int(x.side)==1 else "A"}],x.ts)

    it=file_trades(day); meta=metas[-1]
    cash=START; pos=None; watch=None; trades=[]; next_decision=day.timestamp(); last=None
    entries=reentries=pyramid_adds=flow_exits=h1_exits=0
    maxeq=START; maxdd=0.0; decision_count=0; phase_counts={}
    for x in it:
        if x.ts>=end.timestamp(): break
        last=x; tid+=1
        bucket_update(h1d,x,3600); bucket_update(m15d,x,900)
        obs.heartbeat(x.ts)
        obs.ingest_trades([{"coin":SYMBOL,"px":x.price,"sz":x.quantity,"time":x.ts*1000,"tid":"d"+str(tid),"side":"B" if int(x.side)==1 else "A"}],x.ts)
        if x.ts<next_decision: continue
        next_decision=x.ts+DECISION_CADENCE; decision_count+=1

        hr=rows(h1d,160); mr=rows(m15d,80)
        analysis=analyze(hr,int(x.ts*1000),SYMBOL)
        side_for_m15=int((pos or watch or {}).get("side") or analysis.get("entry_side") or 1)
        m15=analyze_m15(mr,int(x.ts*1000),side_for_m15)
        flow=obs.flow_context(SYMBOL,x.ts)

        if pos:
            pos,_liq=update_path(pos,x.price)
            if pos["side"]>0: pos["best_mark"]=max(pos.get("best_mark",pos["entry"]),x.price)
            else: pos["best_mark"]=min(pos.get("best_mark",pos["entry"]),x.price)

            # Exact 224d pyramiding.
            side=int(pos["side"]); favorable=side*(x.price/pos["entry"]-1.0); roe=favorable*LEV*100.0
            f=pos.setdefault("features",{})
            last_add=float(f.get("pyramid_last_add_epoch") or 0)
            same_h1=analysis.get("ready") and analysis.get("anchor_confirmed") and int(analysis.get("entry_side") or 0)==side
            if same_h1 and flow.get("trade_data_fresh") and x.ts-last_add>=S1_PYRAMID_COOLDOWN_SECONDS and roe>=S1_PYRAMID_MIN_ROE_PCT:
                try:
                    i60=side*float(flow.get("flow_imbalance")); i180=side*float(flow.get("flow_imbalance_180s")); i300=side*float(flow.get("flow_imbalance_300s"))
                    aligned=float(flow.get("trade_coverage_seconds") or 0)>=300 and i60>=.12 and i180>=.08 and i300>=.08
                except (TypeError,ValueError): aligned=False
                if aligned:
                    equity=mtm(cash,pos,x.price); add_margin=max(.01,equity*S1_PYRAMID_MARGIN_FRACTION)
                    add_notional=add_margin*LEV; oldn=pos["notional"]; newn=oldn+add_notional
                    pos["entry"]=(pos["entry"]*oldn+x.price*add_notional)/newn
                    pos["notional"]=newn; pos["margin"]+=add_margin
                    f["pyramid_last_add_epoch"]=x.ts; f["pyramid_add_count"]=int(f.get("pyramid_add_count") or 0)+1
                    pyramid_adds+=1

            entry_candle=int(pos.get("signal_candle_time") or 0); signal=int(analysis.get("signal_candle_time") or 0)
            h1reason=None
            if analysis.get("ready") and analysis.get("anchor_confirmed") and signal>entry_candle>0 and int(analysis.get("entry_side") or 0)==-int(pos["side"]):
                h1reason="opposite_h1_local_emergency_exit"
            if not h1reason and analysis.get("ready"):
                h1reason=position_exit(pos,analysis,x.price)
            weak=weakening_exit(pos,m15,x.price,flow)
            if h1reason:
                cash,watch=close_trade(cash,pos,x.price,x.ts,h1reason,trades,False); pos=None; h1_exits+=1
            elif weak:
                cash,watch=close_trade(cash,pos,x.price,x.ts,"m1_m3_confirmed_counterflow_exit",trades,True,"WAIT_PULLBACK")
                pos=None; flow_exits+=1

        if pos is None:
            if watch:
                if analysis.get("ready") and int(analysis.get("entry_side") or 0)==-int(watch.get("side") or 0):
                    watch=None
                else:
                    watch=update_watch(watch,x.price,m15,flow,x.ts)
                    ph=(watch.get("context") or {}).get("phase"); phase_counts[ph]=phase_counts.get(ph,0)+1
            if watch:
                side=int(watch["side"])
                if reentry_ready(side,m15,x.price,watch,flow) and not analysis.get("entry_blocked"):
                    equity=cash; margin=max(.01,equity*MARGIN); notional=margin*LEV
                    pos={"side":side,"entry":x.price,"opened":x.ts,"notional":notional,"margin":margin,"leverage":LEV,
                         "signal_candle_time":int(analysis.get("signal_candle_time") or 0),"kind":"REENTRY",
                         "features":{**dict(analysis),"entry_kind":"REENTRY","estimated_round_trip_cost_move":2*FEE+.0004,
                                     "mfe_price_move":0.0,"mae_price_move":0.0},"best_mark":x.price}
                    reentries+=1; watch=None
            elif analysis.get("ready") and analysis.get("anchor_confirmed") and analysis.get("h1_direction_anchor") and not analysis.get("entry_blocked") and fresh_h1_trigger(analysis,x.ts):
                side=int(analysis.get("entry_side") or 0)
                if side in (-1,1):
                    margin=max(.01,cash*MARGIN); notional=margin*LEV
                    pos={"side":side,"entry":x.price,"opened":x.ts,"notional":notional,"margin":margin,"leverage":LEV,
                         "signal_candle_time":int(analysis.get("signal_candle_time") or 0),"kind":"H1_CONFIRMED",
                         "features":{**dict(analysis),"entry_kind":"H1_CONFIRMED","estimated_round_trip_cost_move":2*FEE+.0004,
                                     "mfe_price_move":0.0,"mae_price_move":0.0},"best_mark":x.price}
                    entries+=1

        eq=mtm(cash,pos,x.price); maxeq=max(maxeq,eq); maxdd=max(maxdd,1-eq/maxeq)

    if pos and last:
        cash,_=close_trade(cash,pos,last.price,last.ts,"EOD_MARK",trades,False); pos=None

    mfe=sum(t["mfe_net_pnl"] for t in trades); give=sum(t["giveback_vs_mfe"] for t in trades)
    result={"symbol":SYMBOL,"date":"2026-11-02","strategy_commit":"224dff69db51da2d426fddf4ffc674c94f16349e",
      "strategy":"Exact Strategy 1 — Restored Caterpillar runtime semantics from profitable 29-30 Oct code",
      "start":START,"final":cash,"pnl":cash-START,"return_pct":(cash/START-1)*100,
      "trades":len(trades),"wins":sum(t["pnl"]>0 for t in trades),"losses":sum(t["pnl"]<=0 for t in trades),
      "entries":entries,"reentries":reentries,"pyramid_adds":pyramid_adds,"flow_exits":flow_exits,"h1_exits":h1_exits,
      "max_drawdown_pct":maxdd*100,"mfe_net_sum":mfe,"giveback_vs_mfe_sum":give,
      "decision_cadence_seconds":DECISION_CADENCE,"watch_phase_counts":phase_counts,
      "fees_model":"original paper_pnl: 4.5 bps each leg; no added slippage/funding",
      "exactness_notes":["H1/M15 functions imported from historical_224d snapshot","flow uses historical market_data.RollingMarketData 5-second buckets","224d app helper thresholds copied without repair","known phase-name behavior preserved; no strategy fix added"],
      "data":meta}
    (a.output/"RESULT.json").write_text(json.dumps(result,indent=2))
    (a.output/"TRADES.json").write_text(json.dumps(trades,indent=2))
    print("EXACT_224D_WLD_RESULT "+json.dumps(result),flush=True)

if __name__=="__main__": main()
