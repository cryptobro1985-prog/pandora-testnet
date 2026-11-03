from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import deque
import argparse,json,csv,gzip
from concurrent.futures import ThreadPoolExecutor
from research.caterpillar.caterpillar.sources import Archives,archive_row
from scripts.historical_848_hype_h1_swing import analyze,position_exit,update_path
from scripts.historical_848_local_order_flow import initial_entry_candidate,entry_candidate,pressure_exit,update_watch,reentry_ready

SYMBOL="WLD"; START=500.; MARGIN=.20; LEV=25.; FEE=.00045
ENTRY_CADENCE=10.; RISK_CADENCE=.5 # historical 848 loop cadences

def pnl(n,e,x,s):
    out=n*x/e
    return (out-n)*s-FEE*(n+out)
def bucket(d,x,sec):
    k=int(x.ts//sec)*sec;b=d.get(k)
    if b is None:d[k]={"t":k*1000,"T":(k+sec)*1000-1,"o":x.price,"h":x.price,"l":x.price,"c":x.price,"v":x.quantity}
    else:b["h"]=max(b["h"],x.price);b["l"]=min(b["l"],x.price);b["c"]=x.price;b["v"]+=x.quantity
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    src=Archives(a.cache);day=datetime(2026,11,2,tzinfo=timezone.utc);end=day+timedelta(days=1)
    days=[day-timedelta(days=i) for i in range(5,-1,-1)]
    with ThreadPoolExecutor(max_workers=6) as pool: got=list(pool.map(lambda d:src.obtain(SYMBOL,d),days))
    paths={d:p for d,(p,m) in zip(days,got)};meta=got[-1][1]
    def trades(d):
        with gzip.open(paths[d],"rt",newline="") as h:
            for line,row in enumerate(csv.DictReader(h),2):yield archive_row(SYMBOL,row,line)
    h1={}
    for d in days[:-1]:
        for x in trades(d):bucket(h1,x,3600)
    # exact 848 flow_context uses 5s buckets; warm continuously for 10m before day.
    fb={};warm=day.timestamp()-600;first=warm
    def ingest(x):
        i=int(x.ts//5);b=fb.get(i);v=x.price*x.quantity;j=0 if int(x.side)==1 else 1
        if b is None:b=fb[i]=[0.,0.,0,x.ts,x.price,x.ts,x.price]
        b[j]+=v;b[2]+=1
        if x.ts<b[3]:b[3],b[4]=x.ts,x.price
        if x.ts>b[5]:b[5],b[6]=x.ts,x.price
    for x in trades(day-timedelta(days=1)):
        if x.ts>=warm:ingest(x)
    def flow(ts):
        endi=int(ts//5)
        def vol(sec):
            z=[fb.get(i,(0.,0.,0)) for i in range(endi-sec//5+1,endi+1)]
            return sum(q[0] for q in z),sum(q[1] for q in z),sum(q[2] for q in z)
        def im(b,s):return (b-s)/(b+s) if b+s else 0.
        b15,s15,c15=vol(15);b30,s30,c30=vol(30);b60,s60,c60=vol(60)
        o={"trade_data_fresh":True,"latest_trade_age_seconds":0.,"trade_coverage_seconds":ts-first,
           "buy_volume_15s":b15,"sell_volume_15s":s15,"trade_count_15s":c15,
           "buy_volume_30s":b30,"sell_volume_30s":s30,"trade_count_30s":c30,
           "buy_volume_60s":b60,"sell_volume_60s":s60,"trade_count_60s":c60,
           "flow_imbalance_15s":im(b15,s15),"flow_imbalance_30s":im(b30,s30),"flow_imbalance":im(b60,s60),
           "volume_window_end_epoch":ts}
        if ts-first>=300:
            b,s,c=vol(300);o.update(buy_volume_300s=b,sell_volume_300s=s,trade_count_300s=c,flow_imbalance_300s=im(b,s))
        return o
    cash=START;pos=None;watch=None;out=[];analysis=None;next_entry=day.timestamp();next_risk=day.timestamp();last=None
    entries=reentries=flow_exits=h1_exits=liq=0;maxeq=START;maxdd=0.
    for x in trades(day):
        if x.ts>=end.timestamp():break
        last=x;bucket(h1,x,3600);ingest(x)
        # risk loop ran every .5s: MFE/MAE path + executed-flow exit.
        if x.ts>=next_risk:
            next_risk=x.ts+RISK_CADENCE
            f=flow(x.ts)
            if pos:
                pos,liquid=update_path(pos,x.price)
                reason=pressure_exit(pos,None,x.price,f)
                if reason or liquid:
                    why=reason or "paper_liquidation_proxy";p=pnl(pos["notional"],pos["entry"],x.price,pos["side"]);cash+=p
                    best=pos.get("features",{}).get("mfe_price_move",0.);mfe_move=max(0.,float(best or 0.));mfe_price=pos["entry"]*(1+mfe_move*pos["side"]);m=pnl(pos["notional"],pos["entry"],mfe_price,pos["side"])
                    out.append({**pos,"exit":x.price,"closed":x.ts,"pnl":p,"reason":why,"mfe_net_pnl":m,"giveback_vs_mfe":m-p})
                    if reason:
                        watch={"side":pos["side"],"origin_signal_candle":int(pos.get("signal_candle_time") or 0),"exit_price":x.price,"exit_at":x.ts,"reentries":int(pos.get("features",{}).get("swing_reentries",0) or 0),
                               "context":{"phase":"WAIT_PULLBACK","counter_pressure_seen":False}}
                        flow_exits+=1
                    else:watch=None;liq+=1
                    pos=None
        # canonical scanner/entry/reentry loop every 10s.
        if x.ts>=next_entry:
            next_entry=x.ts+ENTRY_CADENCE
            analysis=analyze([h1[k] for k in sorted(h1)[-160:]],int(x.ts*1000),SYMBOL)
            f=flow(x.ts)
            if pos and analysis.get("ready"):
                pa=int(pos.get("signal_candle_time") or 0);aa=int(analysis.get("signal_candle_time") or 0)
                reason=("opposite_h1_local_emergency_exit" if analysis.get("anchor_confirmed") and aa>pa>0 and int(analysis.get("entry_side") or 0)==-int(pos["side"]) else position_exit(pos,analysis,x.price))
                if reason:
                    p=pnl(pos["notional"],pos["entry"],x.price,pos["side"]);cash+=p
                    best=pos.get("features",{}).get("mfe_price_move",0.);mfe_price=pos["entry"]*(1+max(0.,float(best or 0.))*pos["side"]);m=pnl(pos["notional"],pos["entry"],mfe_price,pos["side"])
                    out.append({**pos,"exit":x.price,"closed":x.ts,"pnl":p,"reason":reason,"mfe_net_pnl":m,"giveback_vs_mfe":m-p});pos=None;watch=None;h1_exits+=1
            if pos is None and analysis.get("ready") and analysis.get("h1_direction_anchor") and not analysis.get("entry_blocked"):
                side=int(analysis.get("entry_side") or 0)
                if watch and int(watch.get("side") or 0)==-side:watch=None
                kind=None
                if watch:
                    watch=update_watch(watch,x.price,None,f,x.ts)
                    if reentry_ready(side,None,x.price,watch,f,x.ts) and entry_candidate(SYMBOL,analysis,None,f,x.ts)["eligible"]:kind="REENTRY"
                elif initial_entry_candidate(SYMBOL,analysis,None,f,x.ts)["eligible"]:kind="ORDER_FLOW"
                if kind:
                    margin=max(.01,cash*MARGIN);pos={"side":side,"entry":x.price,"opened":x.ts,"notional":margin*LEV,"margin":margin,"leverage":LEV,
                      "signal_candle_time":int(analysis.get("signal_candle_time") or 0),"kind":kind,
                      "features":{**dict(analysis),"entry_kind":kind,"estimated_round_trip_cost_move":2*FEE+.0004,"mfe_price_move":0.,"mae_price_move":0.,"swing_reentries":(int(watch.get("reentries") or 0)+1 if watch else 0)}}
                    if kind=="REENTRY":reentries+=1
                    else:entries+=1
                    watch=None
        eq=cash+(pnl(pos["notional"],pos["entry"],x.price,pos["side"]) if pos else 0.);maxeq=max(maxeq,eq);maxdd=max(maxdd,1-eq/maxeq)
    if pos and last:
        p=pnl(pos["notional"],pos["entry"],last.price,pos["side"]);cash+=p
        best=pos.get("features",{}).get("mfe_price_move",0.);mfe_price=pos["entry"]*(1+max(0.,float(best or 0.))*pos["side"]);m=pnl(pos["notional"],pos["entry"],mfe_price,pos["side"])
        out.append({**pos,"exit":last.price,"closed":last.ts,"pnl":p,"reason":"EOD_MARK","mfe_net_pnl":m,"giveback_vs_mfe":m-p})
    r={"symbol":SYMBOL,"date":"2026-11-02","strategy_commit":"848b3c6261bee5b0590a547132c3f236a9a319c3","strategy":"Actual Oct-29 profitable-session Caterpillar runtime snapshot",
       "start":START,"final":cash,"pnl":cash-START,"return_pct":(cash/START-1)*100,"trades":len(out),"wins":sum(z["pnl"]>0 for z in out),"losses":sum(z["pnl"]<=0 for z in out),
       "entries":entries,"reentries":reentries,"flow_exits":flow_exits,"h1_exits":h1_exits,"liquidation_proxy_exits":liq,"max_drawdown_pct":maxdd*100,
       "mfe_net_sum":sum(z["mfe_net_pnl"] for z in out),"giveback_vs_mfe_sum":sum(z["giveback_vs_mfe"] for z in out),
       "fees_model":"4.5bps each leg; no added slippage/funding","cadence":{"risk_seconds":RISK_CADENCE,"entry_h1_seconds":ENTRY_CADENCE},
       "exact_strategy_rules":{"flow":"15s/30s/60s executed aggressor control exactly as commit 848b3c6","m15":"not an execution gate in local_order_flow.py","pyramiding":"absent in this snapshot"},
       "data":meta}
    (a.output/"RESULT.json").write_text(json.dumps(r,indent=2));(a.output/"TRADES.json").write_text(json.dumps(out,indent=2));print("PROFITABLE_848_WLD_RESULT "+json.dumps(r),flush=True)
if __name__=="__main__":main()
