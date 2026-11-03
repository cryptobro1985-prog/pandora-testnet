from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import deque
import argparse,json
from research.caterpillar.caterpillar.sources import Archives
from scripts.historical_224d_hype_h1_swing import analyze,position_exit,update_path
from scripts.historical_9ce_local_order_flow import initial_entry_candidate,entry_candidate,pressure_exit,update_watch,reentry_ready

SYMBOL="WLD"; START=500.; MARGIN=.20; LEV=25.; FEE=.00045
FAST_CADENCE=.5; H1_SCAN_CADENCE=10.

def candles_from_trades(src,start_day,end_day,seconds):
    d={}; day=start_day
    while day<=end_day:
        it,_=src.trades(SYMBOL,day)
        for x in it:
            k=int(x.ts//seconds)*seconds; b=d.get(k)
            if b is None:d[k]={"t":k*1000,"T":(k+seconds)*1000-1,"o":x.price,"h":x.price,"l":x.price,"c":x.price,"v":x.quantity}
            else:b["h"]=max(b["h"],x.price);b["l"]=min(b["l"],x.price);b["c"]=x.price;b["v"]+=x.quantity
        day+=timedelta(days=1)
    return [d[k] for k in sorted(d)]

def paper_pnl(n,e,x,s):
    out=n*(x/e); return (out-n)*s-FEE*(n+out)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    src=Archives(a.cache); day=datetime(2026,11,2,tzinfo=timezone.utc); end=day+timedelta(days=1)
    h1=candles_from_trades(src,day-timedelta(days=5),day,3600)
    # Warm the exact rolling flow with the final five minutes before the test day.
    warm_it,_=src.trades(SYMBOL,day-timedelta(days=1))
    windows={60:deque(),180:deque(),300:deque()}; sums={60:[0.,0.],180:[0.,0.],300:[0.,0.]}
    warm_cut=day.timestamp()-300
    for x in warm_it:
        if x.ts<warm_cut:continue
        if x.ts>=day.timestamp():break
        val=x.price*x.quantity; idx=0 if int(x.side)==1 else 1
        for sec in windows:
            windows[sec].append((x.ts,idx,val));sums[sec][idx]+=val
    first_trade_ts=min((q[0][0] for q in windows.values() if q),default=None)
    it,meta=src.trades(SYMBOL,day)
    cash=START;pos=None;watch=None;trades=[];next_fast=day.timestamp();next_h1=day.timestamp();analysis=None;last=None
    maxeq=START;maxdd=0.; entries=0;reentries=0; h1_exits=0;flow_exits=0;liqs=0
    for t in it:
        if t.ts>=end.timestamp():break
        last=t; val=t.price*t.quantity; idx=0 if int(t.side)==1 else 1
        for sec,q in windows.items():
            q.append((t.ts,idx,val));sums[sec][idx]+=val
            cutoff=t.ts-sec
            while q and q[0][0]<cutoff:
                _,j,v=q.popleft();sums[sec][j]-=v
        if first_trade_ts is None:first_trade_ts=t.ts
        if t.ts>=next_h1:
            analysis=analyze(h1,int(t.ts*1000),SYMBOL);next_h1=t.ts+H1_SCAN_CADENCE
            if pos and analysis.get("ready"):
                pa=int(pos.get("signal_candle_time") or 0); aa=int(analysis.get("signal_candle_time") or 0)
                reason=("opposite_h1_local_emergency_exit" if analysis.get("anchor_confirmed") and aa>pa>0 and int(analysis.get("entry_side") or 0)==-int(pos["side"]) else position_exit(pos,analysis,t.price))
                if reason:
                    pnl=paper_pnl(pos["notional"],pos["entry"],t.price,pos["side"]);cash+=pnl
                    best=pos.get("best_mark",pos["entry"]);mfe_net=paper_pnl(pos["notional"],pos["entry"],best,pos["side"])
                    trades.append({**pos,"exit":t.price,"closed":t.ts,"pnl":pnl,"reason":reason,"mfe_net_pnl":mfe_net,"giveback_vs_mfe":mfe_net-pnl})
                    pos=None;watch=None;h1_exits+=1
            if watch and analysis.get("ready") and int(analysis.get("entry_side") or 0)==-int(watch.get("side") or 0):
                watch=None
        if t.ts<next_fast:continue
        next_fast=t.ts+FAST_CADENCE
        if not analysis or not analysis.get("ready") or not analysis.get("anchor_confirmed"):continue
        def imb(sec):
            b,s=sums[sec]; return (b-s)/(b+s) if b+s else 0.
        coverage=max(0.,t.ts-first_trade_ts) if first_trade_ts is not None else 0.
        f={"trade_data_fresh":True,"latest_trade_age_seconds":0.,"trade_coverage_seconds":coverage,
           "flow_imbalance":imb(60),"flow_imbalance_180s":imb(180) if coverage>=180 else None,
           "flow_imbalance_300s":imb(300) if coverage>=300 else None,
           "volume_window_end_epoch":t.ts,"price_return_300s":None}
        if pos:
            pos,liq=update_path(pos,t.price)
            if pos["side"]>0:
                if t.price>pos.get("best_mark",pos["entry"]):pos["best_mark"]=t.price
            else:
                if t.price<pos.get("best_mark",pos["entry"]):pos["best_mark"]=t.price
            reason=pressure_exit(pos,None,t.price,f)
            if reason or liq:
                why=reason or "paper_liquidation_proxy";pnl=paper_pnl(pos["notional"],pos["entry"],t.price,pos["side"]);cash+=pnl
                best=pos.get("best_mark",pos["entry"]);mfe_net=paper_pnl(pos["notional"],pos["entry"],best,pos["side"])
                trades.append({**pos,"exit":t.price,"closed":t.ts,"pnl":pnl,"reason":why,"mfe_net_pnl":mfe_net,"giveback_vs_mfe":mfe_net-pnl})
                if reason:
                    watch={"side":pos["side"],"origin_signal_candle":int(pos.get("signal_candle_time") or 0),"exit_price":t.price,"exit_at":t.ts,"reentries":int(pos.get("reentries") or 0),
                           "context":{"phase":"WAIT_RESUMPTION","counter_pressure_seen":True,"last_opposite_trade_epoch":t.ts,"flow_context":f.copy()}}
                    flow_exits+=1
                else:watch=None;liqs+=1
                pos=None
        if pos is None:
            side=int((watch or {}).get("side") or analysis.get("entry_side") or 0)
            if watch:
                if int(analysis.get("entry_side") or 0)==-side:watch=None
                else:watch=update_watch(watch,t.price,None,f,t.ts)
            if watch:
                ok=reentry_ready(side,None,t.price,watch,f,t.ts) and entry_candidate(SYMBOL,analysis,None,f,t.ts)["eligible"]
                kind="REENTRY"
            else:
                ok=initial_entry_candidate(SYMBOL,analysis,None,f,t.ts)["eligible"];kind="ENTRY";side=int(analysis.get("entry_side") or 0)
            if ok and side in (-1,1):
                margin=max(.01,cash*MARGIN);notional=margin*LEV
                pos={"side":side,"entry":t.price,"opened":t.ts,"notional":notional,"margin":margin,"leverage":LEV,
                     "signal_candle_time":int(analysis.get("signal_candle_time") or 0),"kind":kind,"reentries":(int((watch or {}).get("reentries") or 0)+1 if kind=="REENTRY" else 0),
                     "features":{"mfe_price_move":0.,"mae_price_move":0.},"best_mark":t.price}
                if kind=="ENTRY":entries+=1
                else:reentries+=1
                watch=None
        if pos:
            eq=cash+paper_pnl(pos["notional"],pos["entry"],t.price,pos["side"]);maxeq=max(maxeq,eq);maxdd=max(maxdd,1-eq/maxeq)
    if pos and last:
        pnl=paper_pnl(pos["notional"],pos["entry"],last.price,pos["side"]);cash+=pnl;best=pos.get("best_mark",pos["entry"]);mfe_net=paper_pnl(pos["notional"],pos["entry"],best,pos["side"])
        trades.append({**pos,"exit":last.price,"closed":last.ts,"pnl":pnl,"reason":"EOD_MARK","mfe_net_pnl":mfe_net,"giveback_vs_mfe":mfe_net-pnl})
    mfe_sum=sum(x["mfe_net_pnl"] for x in trades);giveback=sum(x["giveback_vs_mfe"] for x in trades)
    r={"symbol":SYMBOL,"date":"2026-11-02","strategy_commit":"9ce11ede1b2c0776c7f43b9e8b775737dbad018a",
       "strategy":"Exact profitable Caterpillar H1 + pure executed M1/M3/M5 control","start":START,"final":cash,"pnl":cash-START,"return_pct":(cash/START-1)*100,
       "trades":len(trades),"wins":sum(x["pnl"]>0 for x in trades),"losses":sum(x["pnl"]<=0 for x in trades),"entries":entries,"reentries":reentries,
       "flow_exits":flow_exits,"h1_exits":h1_exits,"liquidation_proxy_exits":liqs,"max_drawdown_pct":maxdd*100,
       "mfe_net_sum":mfe_sum,"giveback_vs_mfe_sum":giveback,"fees_model":"original paper_pnl 4.5bps each leg; no added slippage",
       "decision_cadence":{"fast_flow_seconds":FAST_CADENCE,"h1_scan_seconds":H1_SCAN_CADENCE},
       "rules":{"entry":"all AVAILABLE M1/M3/M5 aligned with confirmed H1 side; M3 joins after 180s, M5 after 300s","exit":"all AVAILABLE M1/M3/M5 opposite","reentry":"after witnessed opposite control, later all AVAILABLE M1/M3/M5 realign","m15":"never gates Strategy 1"},
       "data":meta}
    (a.output/"RESULT.json").write_text(json.dumps(r,indent=2));(a.output/"TRADES.json").write_text(json.dumps(trades,indent=2));print("EXACT_9CE_WLD_RESULT "+json.dumps(r),flush=True)
if __name__=="__main__":main()
