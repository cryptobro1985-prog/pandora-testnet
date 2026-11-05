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
LEVERAGE=25.0
MARGIN_FRACTION=0.20
NOTIONAL_MULTIPLIER=LEVERAGE*MARGIN_FRACTION
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

def bars_from_minutes(minutes, seconds):
    groups=defaultdict(list)
    for r in minutes:
        groups[int(r["ts"]//seconds)*seconds].append(r)
    out=[]
    for t,rs in sorted(groups.items()):
        rs.sort(key=lambda x:x["ts"])
        out.append({"ts":t,"open":rs[0]["open"],"high":max(x["high"] for x in rs),
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

def build_signals(m15,h1):
    # EMA cross is evaluated on CLOSED 15m bars.
    c15=[x["close"] for x in m15]
    e6,e20=ema(c15,6),ema(c15,20)

    # MACD line is evaluated only from CLOSED H1 bars.
    ch1=[x["close"] for x in h1]
    e12,e26=ema(ch1,12),ema(ch1,26)
    macd=[a-b for a,b in zip(e12,e26)]
    macd_by_available_ts={h1[i]["ts"]+3600:macd[i] for i in range(len(h1))}

    signals=[]
    raw_up=raw_down=0
    filtered_up=filtered_down=0
    last_macd=None
    h1_avail=sorted(macd_by_available_ts)
    j=0
    for i in range(1,len(m15)-1):
        signal_available_ts=m15[i]["ts"]+900
        while j<len(h1_avail) and h1_avail[j]<=signal_available_ts:
            last_macd=macd_by_available_ts[h1_avail[j]]
            j+=1
        if last_macd is None:
            continue
        cross_up=e6[i-1]<=e20[i-1] and e6[i]>e20[i]
        cross_down=e6[i-1]>=e20[i-1] and e6[i]<e20[i]
        raw_up += int(cross_up)
        raw_down += int(cross_down)
        up=cross_up and last_macd>0
        dn=cross_down and last_macd<0
        filtered_up += int(up)
        filtered_down += int(dn)
        if not (up or dn):
            continue
        # Enter at the next 15m open, exactly when the closed bar signal becomes known.
        enter_ts=signal_available_ts
        signals.append({"signal_ts":signal_available_ts,"enter_ts":enter_ts,"side":1 if up else -1,
                        "macd_h1":last_macd,"ema6_m15":e6[i],"ema20_m15":e20[i]})
    return signals, {
        "raw_up":raw_up,"raw_down":raw_down,"raw_total":raw_up+raw_down,
        "filtered_up":filtered_up,"filtered_down":filtered_down,
        "filtered_total":filtered_up+filtered_down
    }

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
            ret=(1-x/e)-2*FEE
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

def run_every_signal(minutes, signals, sl, tp, start_ts, end_ts):
    selected=[r for r in minutes if start_ts<=r["ts"]<end_ts]
    if not selected: return None
    ts_sorted=[r["ts"] for r in selected]
    by_ts={r["ts"]:r for r in selected}
    idx={t:i for i,t in enumerate(ts_sorted)}
    equity=START_EQUITY; peak=equity; maxdd=0.0; trades=[]
    for s in signals:
        t=s["enter_ts"]
        if t<start_ts or t>=end_ts or t not in by_ts: continue
        entry=by_ts[t]["open"]; side=s["side"]
        last=selected[-1]; exit_px=last["close"]; exit_ts=last["ts"]; reason="period_end"
        for tt in ts_sorted[idx[t]:]:
            r=by_ts[tt]
            if side==1:
                stop=entry*(1-sl); take=entry*(1+tp)
                if r["low"]<=stop: exit_px=stop; exit_ts=tt; reason="stop"; break
                if r["high"]>=take: exit_px=take; exit_ts=tt; reason="take"; break
            else:
                stop=entry*(1+sl); take=entry*(1-tp)
                if r["high"]>=stop: exit_px=stop; exit_ts=tt; reason="stop"; break
                if r["low"]<=take: exit_px=take; exit_ts=tt; reason="take"; break
        ret=((exit_px/entry-1) if side==1 else (1-exit_px/entry))-2*FEE
        equity*=max(0.0,1+ret)
        trades.append({"side":side,"ret":ret,"reason":reason,"entry_ts":t,"exit_ts":exit_ts})
        peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak if peak else 1)
    wins=sum(x["ret"]>0 for x in trades)
    gp=sum(max(x["ret"],0) for x in trades); gl=-sum(min(x["ret"],0) for x in trades)
    return {"final":equity,"return_pct":(equity/START_EQUITY-1)*100,"trades":len(trades),"wins":wins,
            "win_rate":wins/len(trades)*100 if trades else 0.0,"max_dd_pct":maxdd*100,
            "profit_factor":gp/gl if gl>0 else None,
            "stops":sum(x["reason"]=="stop" for x in trades),"takes":sum(x["reason"]=="take" for x in trades)}


def run_levered_portfolio(minutes, signals, sl, tp, start_ts, end_ts):
    """One live HYPE position at a time. Every qualifying signal closes/replaces any
    existing position at the signal bar open. New trade uses 20% of current equity
    as margin at 25x => 5x account notional. Fees are charged on notional both sides.
    """
    rows=[r for r in minutes if start_ts<=r["ts"]<end_ts]
    if not rows:
        return None
    sigs={s["enter_ts"]:s for s in signals if start_ts<=s["enter_ts"]<end_ts}
    equity=START_EQUITY
    peak=equity
    maxdd=0.0
    trades=[]
    pos=None

    def close_pos(exit_px, exit_ts, reason):
        nonlocal equity, peak, maxdd, pos
        if pos is None:
            return
        price_ret=(exit_px/pos["entry"]-1.0)*pos["side"]
        gross_pnl=pos["notional"]*price_ret
        fees=pos["notional"]*FEE*2.0
        pnl=gross_pnl-fees
        before=equity
        equity += pnl
        trades.append({
            "side":pos["side"],"entry":pos["entry"],"exit":exit_px,
            "entry_ts":pos["ts"],"exit_ts":exit_ts,"reason":reason,
            "price_return":price_ret,"gross_pnl":gross_pnl,"fees":fees,
            "pnl":pnl,"equity_before":before,"equity_after":equity,
            "account_return_pct":(pnl/before*100.0) if before else None,
        })
        peak=max(peak,equity)
        maxdd=max(maxdd,(peak-equity)/peak if peak>0 else 1.0)
        pos=None

    for r in rows:
        ts=r["ts"]

        # A fresh qualifying EMA/MACD signal is actionable immediately at this M15 open.
        # Close any previous position first so capital is never double-used.
        s=sigs.get(ts)
        if s is not None:
            if pos is not None:
                close_pos(r["open"],ts,"next_signal")
            if equity<=0:
                break
            margin=equity*MARGIN_FRACTION
            notional=margin*LEVERAGE
            pos={"side":s["side"],"entry":r["open"],"ts":ts,
                 "margin":margin,"notional":notional}

        if pos is None:
            continue

        e=pos["entry"]
        if pos["side"]==1:
            stop=e*(1-sl); take=e*(1+tp)
            hit_stop=r["low"]<=stop
            hit_take=r["high"]>=take
        else:
            stop=e*(1+sl); take=e*(1-tp)
            hit_stop=r["high"]>=stop
            hit_take=r["low"]<=take

        # Conservative: if both touched in same minute, stop wins.
        if hit_stop:
            close_pos(stop,ts,"stop")
        elif hit_take:
            close_pos(take,ts,"take")

        if equity<=0:
            break

    if pos is not None and rows:
        close_pos(rows[-1]["close"],rows[-1]["ts"],"period_end")

    wins=sum(t["pnl"]>0 for t in trades)
    gp=sum(max(t["pnl"],0.0) for t in trades)
    gl=-sum(min(t["pnl"],0.0) for t in trades)
    return {
        "final":equity,
        "return_pct":(equity/START_EQUITY-1.0)*100.0,
        "trades":len(trades),
        "wins":wins,
        "win_rate":wins/len(trades)*100.0 if trades else 0.0,
        "max_dd_pct":maxdd*100.0,
        "profit_factor":gp/gl if gl>0 else None,
        "stops":sum(t["reason"]=="stop" for t in trades),
        "takes":sum(t["reason"]=="take" for t in trades),
        "next_signal":sum(t["reason"]=="next_signal" for t in trades),
        "detail":trades,
    }

def main():
    minutes,trade_count=load_minutes()
    m15=bars_from_minutes(minutes,900)
    h1=bars_from_minutes(minutes,3600)
    signals,cross_stats=build_signals(m15,h1)
    print(json.dumps({"dataset":{"minutes":len(minutes),"trades":trade_count,"m15":len(m15),"h1":len(h1),"signals_total":len(signals),"cross_stats":cross_stats,
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
    every=[]
    for sl in SL_GRID:
        for tp in TP_GRID:
            d=run_every_signal(minutes,signals,sl,tp,DISCOVERY_START,SPLIT)
            if d:
                every.append({"sl":sl,"tp":tp,**d})
    every.sort(key=lambda x:(x["final"],-x["max_dd_pct"]),reverse=True)
    every_winner=every[0]
    every_oos=run_every_signal(minutes,signals,every_winner["sl"],every_winner["tp"],SPLIT,END_TS)
    every_full=run_every_signal(minutes,signals,every_winner["sl"],every_winner["tp"],DISCOVERY_START,END_TS)

    levered_results=[]
    for sl in SL_GRID:
        for tp in TP_GRID:
            d=run_levered_portfolio(minutes,signals,sl,tp,DISCOVERY_START,SPLIT)
            if d and d["trades"]>=5:
                levered_results.append({"sl":sl,"tp":tp,**{k:v for k,v in d.items() if k!="detail"}})
    levered_results.sort(key=lambda x:(x["final"],-x["max_dd_pct"]),reverse=True)
    levered_winner=levered_results[0]
    levered_oos=run_levered_portfolio(minutes,signals,levered_winner["sl"],levered_winner["tp"],SPLIT,END_TS)
    levered_full=run_levered_portfolio(minutes,signals,levered_winner["sl"],levered_winner["tp"],DISCOVERY_START,END_TS)

    payload={"assumptions":{"ema":"6/20 M15 close","macd":"12/26 line sign on last closed H1","entry":"next M15 open","fee_per_side":FEE,
                             "same_minute_tp_sl":"stop-first conservative","position":"20% current equity margin at 25x = 5x account notional, compounded"},
             "discovery":{"start":"2026-10-11","end_exclusive":"2026-10-27","top10":top,"winner":winner},
             "oos":{"start":"2026-10-27","end_exclusive":"2026-11-03",**{k:v for k,v in oos.items() if k!="detail"}},
             "full":{"start":"2026-10-11","end_exclusive":"2026-11-03",**{k:v for k,v in full.items() if k!="detail"}},
             "winner_trades":full["detail"],"neighbor_candidates":near,
             "every_qualifying_cross":{"discovery_winner":every_winner,"oos":every_oos,"full":every_full},
             "cross_stats":cross_stats,
             "levered_25x_20pct_margin":{
                 "discovery_top10":levered_results[:10],
                 "winner":levered_winner,
                 "oos":{k:v for k,v in levered_oos.items() if k!="detail"},
                 "full":{k:v for k,v in levered_full.items() if k!="detail"},
                 "full_trades":levered_full["detail"]
             }}
    print("RESULT_JSON="+json.dumps(payload,separators=(",",":"),sort_keys=True),flush=True)
    with open("hype_ema_macd_30d_result.json","w") as f: json.dump(payload,f,indent=2,sort_keys=True)

if __name__=="__main__":
    main()
