from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse, json, math, csv, gzip
from concurrent.futures import ThreadPoolExecutor

from research.caterpillar.caterpillar.sources import Archives, archive_row
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

def flow_profile(flow, side):
    if side not in (-1,1) or not flow.get("trade_data_fresh"): return None
    age=float(flow.get("latest_trade_age_seconds") or 0)
    if age < -1 or age > 15: return None
    raw60=flow.get("flow_imbalance"); raw180=flow.get("flow_imbalance_180s"); raw300=flow.get("flow_imbalance_300s")
    if raw60 is None: return None
    coverage=float(flow.get("trade_coverage_seconds") or 0)
    m1=side*float(raw60); m3=side*float(raw180) if raw180 is not None else None; m5=side*float(raw300) if raw300 is not None else None
    vals=[m1]
    if coverage>=180 and m3 is not None: vals.append(m3)
    if coverage>=300 and m5 is not None: vals.append(m5)
    return {"m1":m1,"m3":m3,"m5":m5,"direct_control":all(x>0 for x in vals),"counter_takeover":all(x<0 for x in vals),
            "resumed":all(x>0 for x in vals),"event_epoch":float(flow.get("volume_window_end_epoch") or 0)-age}

def weakening_exit(pos,m15,mark,flow):
    p=flow_profile(flow,int(pos["side"])) if pos else None
    return "executed_flow_m1_m3_m5_opposite_control_exit" if p and p["counter_takeover"] else None

def reentry_ready(side,m15,mark,watch,flow):
    if side not in (-1,1) or not watch or int(watch.get("side") or 0)!=side: return False
    ctx=watch.get("context") or {}
    if ctx.get("phase")!="WAIT_RESUMPTION" or not ctx.get("counter_pressure_seen"): return False
    p=flow_profile(flow,side)
    opp=ctx.get("last_opposite_trade_epoch")
    return bool(p and p["resumed"] and p["event_epoch"] is not None and opp is not None and p["event_epoch"]>float(opp))

def mtm(cash,pos,mark):
    return cash+(paper_pnl(pos["notional"],pos["entry"],mark,pos["side"]) if pos else 0.0)

def close_trade(cash,pos,mark,ts,reason,trades,arm_watch=False,flow=None):
    pnl=paper_pnl(pos["notional"],pos["entry"],mark,pos["side"]); cash+=pnl
    best=pos.get("best_mark",pos["entry"]); mfe=paper_pnl(pos["notional"],pos["entry"],best,pos["side"])
    trades.append({**pos,"exit":mark,"closed":ts,"pnl":pnl,"reason":reason,"mfe_net_pnl":mfe,"giveback_vs_mfe":mfe-pnl})
    watch=None
    if arm_watch:
        event_epoch=(flow_profile(flow,int(pos["side"])) or {}).get("event_epoch")
        watch={"symbol":SYMBOL,"side":int(pos["side"]),"origin_signal_candle":int(pos.get("signal_candle_time") or 0),
               "exit_price":mark,"exit_at":ts,"reentries":int(pos.get("features",{}).get("swing_reentries",0) or 0),
               "context":{"phase":"WAIT_RESUMPTION","counter_pressure_seen":event_epoch is not None,
                          "last_opposite_trade_epoch":event_epoch}}
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
    def parse_history_day(d):
        hd={}; md={}
        for x in file_trades(d):
            bucket_update(hd,x,3600)
            if d>=day-timedelta(days=1): bucket_update(md,x,900)
        return hd,md
    h1d={}; m15d={}
    with ThreadPoolExecutor(max_workers=5) as pool:
        hist=list(pool.map(parse_history_day,days[:-1]))
    for hd,md in hist:
        h1d.update(hd); m15d.update(md)

    # Exact historical RollingMarketData flow_context bucket arithmetic,
    # implemented directly to avoid per-trade lock/dedup overhead in replay.
    flow_buckets={}; warm_start=day.timestamp()-600
    def flow_ingest(x):
        i=int(x.ts//5); b=flow_buckets.get(i); val=x.price*x.quantity; j=0 if int(x.side)==1 else 1
        if b is None: b=flow_buckets[i]=[0.0,0.0,0,x.ts,x.price,x.ts,x.price]
        b[j]+=val; b[2]+=1
        if x.ts<b[3]: b[3],b[4]=x.ts,x.price
        if x.ts>b[5]: b[5],b[6]=x.ts,x.price
    def flow_context(epoch):
        end=int(epoch//5)
        def vols(seconds):
            rr=[flow_buckets.get(i,(0.,0.,0)) for i in range(end-seconds//5+1,end+1)]
            return sum(z[0] for z in rr),sum(z[1] for z in rr),sum(z[2] for z in rr)
        def imb(b,s): return (b-s)/(b+s) if b+s else 0.0
        cov=max(0.0,epoch-warm_start); b60,s60,c60=vols(60)
        out={"trade_data_fresh":True,"latest_trade_age_seconds":0.0,"trade_coverage_seconds":cov,"volume_window_end_epoch":epoch,
             "flow_imbalance":imb(b60,s60),"trade_count_60s":c60,"observed_notional_60s":b60+s60}
        b15,s15,c15=vols(15); b30,s30,c30=vols(30)
        out.update(flow_imbalance_15s=imb(b15,s15),flow_imbalance_30s=imb(b30,s30),trade_count_15s=c15,trade_count_30s=c30)
        if cov>=180:
            b,s,c=vols(180); out.update(flow_imbalance_180s=imb(b,s),trade_count_180s=c)
        if cov>=300:
            b,s,c=vols(300); out.update(flow_imbalance_300s=imb(b,s),trade_count_300s=c)
        return out
    wit=file_trades(day-timedelta(days=1))
    tid=0
    for x in wit:
        if x.ts<warm_start: continue
        if x.ts>=day.timestamp(): break
        tid+=1; flow_ingest(x)

    it=file_trades(day); meta=metas[-1]
    cash=START; pos=None; watch=None; trades=[]; next_decision=day.timestamp(); last=None
    entries=reentries=pyramid_adds=flow_exits=h1_exits=0
    maxeq=START; maxdd=0.0; decision_count=0; phase_counts={}
    analysis_cache=None; h1_slot=None
    for x in it:
        if x.ts>=end.timestamp(): break
        last=x; tid+=1
        bucket_update(h1d,x,3600); bucket_update(m15d,x,900)
        flow_ingest(x)
        if x.ts<next_decision: continue
        next_decision=x.ts+DECISION_CADENCE; decision_count+=1

        hr=rows(h1d,160); mr=rows(m15d,80)
        slot=int(x.ts//3600)
        if analysis_cache is None or slot!=h1_slot:
            analysis_cache=analyze(hr,int(x.ts*1000),SYMBOL); h1_slot=slot
        analysis=analysis_cache
        side_for_m15=int((pos or watch or {}).get("side") or analysis.get("entry_side") or 1)
        m15=analyze_m15(mr,int(x.ts*1000),side_for_m15)
        flow=flow_context(x.ts)

        if pos:
            pos,_liq=update_path(pos,x.price)
            if pos["side"]>0: pos["best_mark"]=max(pos.get("best_mark",pos["entry"]),x.price)
            else: pos["best_mark"]=min(pos.get("best_mark",pos["entry"]),x.price)

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
                cash,watch=close_trade(cash,pos,x.price,x.ts,weak,trades,True,flow)
                pos=None; flow_exits+=1

        if pos is None:
            if watch:
                if analysis.get("ready") and int(analysis.get("entry_side") or 0)==-int(watch.get("side") or 0):
                    watch=None
                else:
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
            elif analysis.get("ready") and analysis.get("anchor_confirmed") and analysis.get("h1_direction_anchor") and not analysis.get("entry_blocked"):
                side=int(analysis.get("entry_side") or 0); prof=flow_profile(flow,side)
                if side in (-1,1) and prof and prof["direct_control"]:
                    margin=max(.01,cash*MARGIN); notional=margin*LEV
                    pos={"side":side,"entry":x.price,"opened":x.ts,"notional":notional,"margin":margin,"leverage":LEV,
                         "signal_candle_time":int(analysis.get("signal_candle_time") or 0),"kind":"ORDER_FLOW",
                         "features":{**dict(analysis),"entry_kind":"ORDER_FLOW","estimated_round_trip_cost_move":2*FEE+.0004,
                                     "mfe_price_move":0.0,"mae_price_move":0.0},"best_mark":x.price}
                    entries+=1

        eq=mtm(cash,pos,x.price); maxeq=max(maxeq,eq); maxdd=max(maxdd,1-eq/maxeq)

    if pos and last:
        cash,_=close_trade(cash,pos,last.price,last.ts,"EOD_MARK",trades,False); pos=None

    mfe=sum(t["mfe_net_pnl"] for t in trades); give=sum(t["giveback_vs_mfe"] for t in trades)
    result={"symbol":SYMBOL,"date":"2026-11-02","strategy_commit":"9ce11ede1b2c0776c7f43b9e8b775737dbad018a",
      "strategy":"Caterpillar LIVE runtime 9ce11ede — H1 local + pure M1/M3/M5 executed control",
      "start":START,"final":cash,"pnl":cash-START,"return_pct":(cash/START-1)*100,
      "trades":len(trades),"wins":sum(t["pnl"]>0 for t in trades),"losses":sum(t["pnl"]<=0 for t in trades),
      "entries":entries,"reentries":reentries,"pyramid_adds":pyramid_adds,"flow_exits":flow_exits,"h1_exits":h1_exits,
      "max_drawdown_pct":maxdd*100,"mfe_net_sum":mfe,"giveback_vs_mfe_sum":give,
      "decision_cadence_seconds":DECISION_CADENCE,"watch_phase_counts":phase_counts,
      "fees_model":"original paper_pnl: 4.5 bps each leg; no added slippage/funding",
      "exactness_notes":["H1 analyzer blob is identical between 224dff69 and 9ce11ede","entry/exit/reentry semantics copied from local_order_flow.py @ 9ce11ede","flow mirrors market_data.py 5-second bucket arithmetic @ 9ce11ede","single-symbol replay has no multi-symbol margin contention or runtime transport lag"],
      "data":meta}
    (a.output/"RESULT.json").write_text(json.dumps(result,indent=2))
    (a.output/"TRADES.json").write_text(json.dumps(trades,indent=2))
    print("EXACT_9CE_WLD_RESULT "+json.dumps(result),flush=True)

if __name__=="__main__": main()
