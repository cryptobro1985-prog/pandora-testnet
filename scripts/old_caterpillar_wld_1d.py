from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import deque
import argparse,json,math,statistics
from research.caterpillar.caterpillar.sources import Archives
from scripts.historical_224d_hype_h1_swing import analyze,analyze_m15,position_exit,update_path
from scripts.historical_224d_local_caterpillar import update_watch

SYMBOL="WLD"; START=500.; MARGIN=.20; LEV=25.; FEE=.00045

def candles_from_trades(src,start_day,end_day,seconds):
    d={}
    day=start_day
    while day<=end_day:
        it,_=src.trades(SYMBOL,day)
        for x in it:
            k=int(x.ts//seconds)*seconds
            b=d.get(k)
            if b is None:d[k]={"t":k*1000,"T":(k+seconds)*1000-1,"o":x.price,"h":x.price,"l":x.price,"c":x.price,"v":x.quantity}
            else:b["h"]=max(b["h"],x.price);b["l"]=min(b["l"],x.price);b["c"]=x.price;b["v"]+=x.quantity
        day+=timedelta(days=1)
    return [d[k] for k in sorted(d)]

def paper_pnl(n,e,x,s):
    out=n*(x/e);return (out-n)*s-FEE*(n+out)

def flow(buckets,t,sec):
    end=int(t//5);rows=[buckets.get(i,(0.,0.,0)) for i in range(end-sec//5+1,end+1)]
    b=sum(x[0] for x in rows);s=sum(x[1] for x in rows);n=sum(x[2] for x in rows)
    return ((b-s)/(b+s) if b+s else 0.),n

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    src=Archives(a.cache);day=datetime(2026,11,2,tzinfo=timezone.utc);end=day+timedelta(days=1)
    # Exact runtime requested up to 120h H1 history and 12h M15 history.
    h1=candles_from_trades(src,day-timedelta(days=5),day,3600)
    m15=candles_from_trades(src,day-timedelta(days=1),day,900)
    it,meta=src.trades(SYMBOL,day)
    buckets={};since=None;last_trade_ts=None;cash=START;pos=None;watch=None;trades=[];adds=[];next_eval=day.timestamp();last=None;maxeq=START;maxdd=0.;last_anchor=None;cur15=None;cached_a=None;last_h1_slot=None
    for t in it:
        last=t
        bi=int(t.ts//5);bb=buckets.setdefault(bi,[0.,0.,0]);bb[0 if int(t.side)==1 else 1]+=t.price*t.quantity;bb[2]+=1
        if since is None:since=t.ts
        last_trade_ts=t.ts
        floor=bi-65
        for old in [x for x in buckets if x<floor]:del buckets[old]
        k15=int(t.ts//900)*900
        if cur15 is None or cur15["t"]!=k15*1000:
            cur15={"t":k15*1000,"T":(k15+900)*1000-1,"o":t.price,"h":t.price,"l":t.price,"c":t.price,"v":t.quantity}
        else:
            cur15["h"]=max(cur15["h"],t.price);cur15["l"]=min(cur15["l"],t.price);cur15["c"]=t.price;cur15["v"]+=t.quantity
        if t.ts<next_eval:continue
        now=t.ts;next_eval=now+5.
        ms=int(now*1000)
        slot=int(now//3600)\n        if cached_a is None or slot!=last_h1_slot:\n            cached_a=analyze(h1,ms,SYMBOL);last_h1_slot=slot\n        aa=cached_a
        if aa.get("ready") and aa.get("anchor_confirmed") and aa.get("entry_side") in (-1,1):
            if last_anchor is None or int(aa.get("signal_candle_time") or 0)>=int(last_anchor.get("signal_candle_time") or 0):last_anchor=aa
        a1=last_anchor or aa
        side=int((pos or watch or {}).get("side") or a1.get("entry_side") or 1)
        # Runtime sees completed M15 candles plus the causally forming candle, never its future final OHLCV.
        mrows=[x for x in m15 if x["T"]<ms and x["t"]<cur15["t"]]+[dict(cur15)]
        mm=analyze_m15(mrows,ms,side)
        i60,c60=flow(buckets,now,60);i180,c180=flow(buckets,now,180);i300,c300=flow(buckets,now,300)
        coverage=max(0.,now-since) if since is not None else 0
        flowctx={"trade_data_fresh":bool(last_trade_ts is not None and now-last_trade_ts<=15 and coverage>=60),"latest_trade_age_seconds":now-last_trade_ts if last_trade_ts is not None else None,
          "trade_coverage_seconds":coverage,"flow_imbalance":i60,"flow_imbalance_180s":i180 if coverage>=180 else None,
          "flow_imbalance_300s":i300 if coverage>=300 else None,"trade_count_60s":c60,"trade_count_180s":c180,"trade_count_300s":c300}
        if pos:
            pos,_=update_path(pos,t.price)
            # exact _s1_pyramid_add
            pf=pos.setdefault("features",{});fav=pos["side"]*(t.price/pos["entry"]-1);roe=fav*25*100
            aligned=coverage>=300 and pos["side"]*i60>=.12 and pos["side"]*i180>=.08 and pos["side"]*i300>=.08
            same=bool(a1.get("ready") and a1.get("anchor_confirmed") and int(a1.get("entry_side") or 0)==pos["side"])
            if flowctx["trade_data_fresh"] and same and now-float(pf.get("pyramid_last_add_epoch") or 0)>=60 and roe>=20 and aligned:
                # single-symbol MTM equity/free margin, as original comparison account
                unreal=paper_pnl(pos["notional"],pos["entry"],t.price,pos["side"]);eq=cash+unreal;free=eq-pos["margin"];addm=max(.01,eq*.05)
                if free+1e-9>=addm:
                    addn=addm*25;oldn=pos["notional"];pos["entry"]=(pos["entry"]*oldn+t.price*addn)/(oldn+addn);pos["notional"]=oldn+addn;pos["margin"]+=addm;pf["pyramid_last_add_epoch"]=now;pf["pyramid_add_count"]=int(pf.get("pyramid_add_count") or 0)+1;adds.append({"t":now,"price":t.price,"margin":addm,"roe_before":roe})
            h1exit="opposite_h1_local_emergency_exit" if a1.get("ready") and a1.get("anchor_confirmed") and int(a1.get("entry_side") or 0)==-pos["side"] else position_exit(pos,a1,t.price) if a1.get("ready") else None
            weakening=False
            if flowctx["trade_data_fresh"] and coverage>=180 and c60>=5 and c180>=12 and pos["side"]*i60<=-.18 and pos["side"]*i180<=-.08:
                fav=pos["side"]*(t.price/pos["entry"]-1);peak=max(0.,float(pf.get("mfe_price_move") or 0),fav);typ=float(mm.get("median_range_move") or .008);recoil=max(.0007,min(.0018,typ*.12));weakening=(peak-fav>=recoil)
            reason=h1exit or ("m1_m3_confirmed_counterflow_exit" if weakening else None)
            if reason:
                pnl=paper_pnl(pos["notional"],pos["entry"],t.price,pos["side"]);cash+=pnl
                trades.append({**pos,"exit":t.price,"closed":now,"pnl":pnl,"reason":reason,"mfe_move":pf.get("mfe_price_move",0),"mae_move":pf.get("mae_price_move",0)})
                if weakening:watch={"side":pos["side"],"origin_signal_candle":int(pos.get("signal_candle_time") or 0),"exit_price":t.price,"exit_at":now,"reentries":0,"context":{"phase":"WAIT_PULLBACK","counter_pressure_seen":False,"pullback_extreme":t.price,"anchor":pf.copy()}}
                else:watch=None
                pos=None
        else:
            if watch:
                if a1.get("ready") and int(a1.get("entry_side") or 0)==-int(watch["side"]):watch=None
                else:watch=update_watch(watch,t.price,mm,flowctx,now)
            opened=False
            if watch:
                same=int(a1.get("entry_side") or 0)==int(watch["side"])
                fresh=bool(a1.get("anchor_confirmed") and 0<=now-float(a1.get("signal_candle_close_time") or 0)/1000<=120)
                newh=bool(a1.get("ready") and a1.get("h1_direction_anchor") and same and int(a1.get("signal_candle_time") or 0)>int(watch.get("origin_signal_candle") or 0))
                # exact _s1_reentry_ready: phase must literally be WAIT_RESUMPTION
                ctx=watch.get("context") or {};ext=float(ctx.get("pullback_extreme") or watch["exit_price"]);resume=max(.0005,min(.0012,float(mm.get("median_range_move") or .008)*.10))
                rr=bool(ctx.get("phase")=="WAIT_RESUMPTION" and ctx.get("counter_pressure_seen") and flowctx["trade_data_fresh"] and coverage>=300 and
                    side*i60>=.12 and side*i180>=.08 and side*i300>=.08 and int(mm.get("recovery_score") or 0)>=2 and int(mm.get("adverse_score") or 0)<=1 and side*(t.price/ext-1)>=resume)
                if newh and fresh:opened=True;kind="H1_REENTRY"
                elif rr:opened=True;kind="REENTRY"
            else:
                fresh=bool(a1.get("ready") and a1.get("anchor_confirmed") and a1.get("h1_direction_anchor") and 0<=now-float(a1.get("signal_candle_close_time") or 0)/1000<=120)
                if fresh and int(a1.get("entry_side") or 0) in (-1,1):opened=True;kind="H1_CONFIRMED";side=int(a1["entry_side"])
            if opened:
                eq=cash;margin=max(.01,eq*.20);notional=margin*25;pos={"side":side,"entry":t.price,"opened":now,"notional":notional,"margin":margin,"leverage":25.,"signal_candle_time":int(a1.get("signal_candle_time") or 0),"kind":kind,"features":{"mfe_price_move":0.,"mae_price_move":0.,"pyramid_add_count":0}};watch=None
        if pos:
            eq=cash+paper_pnl(pos["notional"],pos["entry"],t.price,pos["side"]);maxeq=max(maxeq,eq);maxdd=max(maxdd,1-eq/maxeq)
    if pos and last:
        pnl=paper_pnl(pos["notional"],pos["entry"],last.price,pos["side"]);cash+=pnl;trades.append({**pos,"exit":last.price,"closed":last.ts,"pnl":pnl,"reason":"EOD_MARK","mfe_move":pos["features"].get("mfe_price_move",0),"mae_move":pos["features"].get("mae_price_move",0)})
    r={"symbol":SYMBOL,"date":"2026-11-02","strategy_commit":"224dff69db51da2d426fddf4ffc674c94f16349e","strategy":"Restored profitable Caterpillar runtime exact thresholds/state semantics","start":START,"final":cash,"pnl":cash-START,"return_pct":(cash/START-1)*100,"trades":len(trades),"wins":sum(x["pnl"]>0 for x in trades),"losses":sum(x["pnl"]<=0 for x in trades),"pyramid_adds":len(adds),"max_drawdown_pct":maxdd*100,"fees_model":"original paper_pnl 4.5bps each leg, no added slippage","data":meta,"notes":"5s decision cadence; Bybit executed trades; H1/M15 candles reconstructed causally from same Bybit tape; exact historical H1/M15 analyzer vendored from commit 224dff69."}
    (a.output/"RESULT.json").write_text(json.dumps(r,indent=2));(a.output/"TRADES.json").write_text(json.dumps(trades,indent=2));print("RESTORED_CATERPILLAR_WLD_RESULT "+json.dumps(r),flush=True)
if __name__=="__main__":main()
\n# exact replay trigger cdd8\n