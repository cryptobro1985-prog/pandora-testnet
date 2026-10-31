#!/usr/bin/env python3
import argparse,csv,datetime as dt,gzip,json,math,os,tempfile,urllib.request
from collections import defaultdict
from h1_structure_legacy import analyze as h1_analyze

FEE=0.00045
LEV=25.0
MARGIN_FRACTION=0.20

def f(x):
    try:
        y=float(x); return y if math.isfinite(y) else None
    except Exception:return None

def trade_epoch(row):
    for k in ("timestamp","time","T","ts"):
        if k in row:
            v=f(row.get(k))
            if v is None: continue
            if v>1e14:return v/1e6
            if v>1e11:return v/1e3
            return v
    return None

def field(row,*names):
    low={str(k).lower():v for k,v in row.items()}
    for n in names:
        if n.lower() in low:return low[n.lower()]
    return None

def download_day(symbol,date):
    pair=symbol+"USDT"
    name=f"{pair}{date.isoformat()}.csv.gz"
    url=f"https://public.bybit.com/trading/{pair}/{name}"
    path=os.path.join("/tmp",name)
    if not os.path.exists(path) or os.path.getsize(path)<50:
        req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-research/1.0"})
        with urllib.request.urlopen(req,timeout=90) as r, open(path,"wb") as out:
            while True:
                chunk=r.read(1024*1024)
                if not chunk:break
                out.write(chunk)
    return path,url

def parse_days(symbol,dates):
    buckets={}
    meta=[]
    for date in dates:
        path,url=download_day(symbol,date)
        accepted=0
        with gzip.open(path,"rt",encoding="utf-8",errors="replace",newline="") as fh:
            reader=csv.DictReader(fh)
            for row in reader:
                ts=trade_epoch(row);price=f(field(row,"price","p"));size=f(field(row,"size","qty","v"))
                side=str(field(row,"side","S") or "").strip().lower()
                if ts is None or price is None or size is None or price<=0 or size<=0:continue
                if side not in ("buy","sell","b","a"):continue
                t=int(ts//5)*5
                b=buckets.get(t)
                if b is None:
                    b={"t":t,"o":price,"h":price,"l":price,"c":price,"buy":0.0,"sell":0.0,"count":0,"volume":0.0}
                    buckets[t]=b
                b["h"]=max(b["h"],price);b["l"]=min(b["l"],price);b["c"]=price
                notion=price*size
                if side in ("buy","b"):b["buy"]+=notion
                else:b["sell"]+=notion
                b["count"]+=1;b["volume"]+=size;accepted+=1
        meta.append({"date":date.isoformat(),"url":url,"trades":accepted,"bytes":os.path.getsize(path)})
    return buckets,meta

def make_h1_rows(buckets):
    groups={}
    for t in sorted(buckets):
        b=buckets[t];k=(t//3600)*3600
        x=groups.get(k)
        if x is None:
            x={"t":k*1000,"T":k*1000+3599999,"o":b["o"],"h":b["h"],"l":b["l"],"c":b["c"],"v":b["volume"]}
            groups[k]=x
        else:
            x["h"]=max(x["h"],b["h"]);x["l"]=min(x["l"],b["l"]);x["c"]=b["c"];x["v"]+=b["volume"]
    return [groups[k] for k in sorted(groups)]

def flow_at(buckets,t,side):
    def win(sec):
        buy=sell=0.0;count=0
        start=t-sec+5
        for q in range(start,t+1,5):
            b=buckets.get(q)
            if b:
                buy+=b["buy"];sell+=b["sell"];count+=b["count"]
        total=buy+sell
        imb=(buy-sell)/total if total>0 else 0.0
        return buy,sell,count,imb
    b15,s15,c15,i15=win(15);b30,s30,c30,i30=win(30);b60,s60,c60,i60=win(60)
    active=(c15>=2 and c30>=4 and c60>=5 and b15+s15>0 and b30+s30>0)
    a15=side*i15;a30=side*i30;a60=side*i60
    return {
      "active":active,"15":a15,"30":a30,"60":a60,
      "counter_takeover":bool(active and a15<=-.15 and a30<=-.10 and (a15<=a60-.08 or a60<=-.08)),
      "resumed":bool(active and a15>=.18 and a30>=.12 and a60>=.08),
      "aligned_control":bool(active and a15>=.12 and a30>=.08),
      "event_epoch":float(t+5),
      "raw":{"i15":i15,"i30":i30,"i60":i60,"c15":c15,"c30":c30,"c60":c60}
    }

def gross_pnl(pos,exit_price):
    move=pos["side"]*(exit_price/pos["entry"]-1.0)
    return pos["notional"]*move

def fees(pos):
    return pos["notional"]*2*FEE

def pnl(pos,exit_price):
    return gross_pnl(pos,exit_price)-fees(pos)

def unrealized(pos,mark):
    return pnl(pos,mark)

def run(symbols,start_date,days):
    start=dt.date.fromisoformat(start_date)
    end=start+dt.timedelta(days=days)
    warm=start-dt.timedelta(days=1)
    dates=[];d=warm
    while d<end:
        dates.append(d);d+=dt.timedelta(days=1)
    start_ts=dt.datetime.combine(start,dt.time(),tzinfo=dt.timezone.utc).timestamp()
    end_ts=dt.datetime.combine(end,dt.time(),tzinfo=dt.timezone.utc).timestamp()

    data={};coverage={}
    for symbol in symbols:
        buckets,meta=parse_days(symbol,dates)
        data[symbol]={"buckets":buckets,"h1":make_h1_rows(buckets)}
        coverage[symbol]=meta
        print("ARCHIVE",symbol,json.dumps(meta,separators=(",",":")),flush=True)

    cash=500.0;positions={};watches={};anchors={};last_price={}
    trades=[];equity_curve=[];peak=500.0;max_dd=0.0
    stats={s:{"pnl":0.0,"trades":0,"wins":0,"reentries":0,"reentry_pnl":0.0,"reentry_wins":0} for s in symbols}
    all_times=range(int(start_ts//5)*5,int(end_ts//5)*5,5)

    def mtm():
        return cash+sum(unrealized(p,last_price.get(s,p["entry"])) for s,p in positions.items())

    def free_margin():
        return mtm()-sum(p["margin"] for p in positions.values())

    def open_pos(symbol,side,mark,t,kind,anchor,watch=None):
        nonlocal cash
        equity=mtm();margin=max(.01,equity*MARGIN_FRACTION)
        if free_margin()+1e-9<margin:return False
        positions[symbol]={
          "symbol":symbol,"side":int(side),"entry":float(mark),"margin":margin,"notional":margin*LEV,
          "leverage":LEV,"opened_t":t,"entry_kind":kind,
          "signal_candle_time":int((anchor or {}).get("signal_candle_time") or 0),
          "watch":json.loads(json.dumps(watch)) if watch else None,
        }
        if watch is not None:watches.pop(symbol,None)
        return True

    def close_pos(symbol,mark,t,reason):
        nonlocal cash
        pos=positions.pop(symbol)
        gross=gross_pnl(pos,mark);fee=fees(pos);value=gross-fee;cash+=value
        row={**pos,"closed_t":t,"exit":mark,"gross_pnl":gross,"fees":fee,"pnl":value,"reason":reason}
        trades.append(row)
        st=stats[symbol];st["pnl"]+=value;st["trades"]+=1;st["wins"]+=int(value>0)
        if pos["entry_kind"]=="REENTRY":
            st["reentries"]+=1;st["reentry_pnl"]+=value;st["reentry_wins"]+=int(value>0)
        return row

    last_anchor_hour={}
    for t in all_times:
        # Update marks and H1 anchors.
        for s in symbols:
            b=data[s]["buckets"].get(t)
            if b:last_price[s]=b["c"]
            hour=t//3600
            if last_anchor_hour.get(s)!=hour:
                last_anchor_hour[s]=hour
                try:
                    a=h1_analyze(data[s]["h1"],int((t+5)*1000),s)
                except Exception:
                    a=None
                if isinstance(a,dict) and a.get("ready") and a.get("anchor_confirmed") and int(a.get("entry_side") or 0) in (-1,1):
                    anchors[s]=a

        for s in symbols:
            mark=last_price.get(s);anchor=anchors.get(s)
            if mark is None or not anchor:continue
            aside=int(anchor.get("entry_side") or 0)
            pos=positions.get(s);watch=watches.get(s)

            if pos:
                if aside==-int(pos["side"]):
                    close_pos(s,mark,t,"opposite_confirmed_h1_local")
                    watches.pop(s,None)
                    continue
                prof=flow_at(data[s]["buckets"],t,int(pos["side"]))
                if prof["counter_takeover"]:
                    exited=close_pos(s,mark,t,"executed_flow_profit_flip_exit" if pnl(pos,mark)>0 else "executed_flow_risk_flip_exit")
                    watches[s]={
                      "side":int(exited["side"]),"exit_price":float(mark),"exit_t":t,
                      "reentries":int((exited.get("watch") or {}).get("reentries",0))+int(exited["entry_kind"]=="REENTRY"),
                      "context":{"phase":"WAIT_PULLBACK","counter_pressure_seen":False,
                                 "pullback_extreme":float(mark),"last_opposite_trade_epoch":None}
                    }
                continue

            if watch:
                wside=int(watch["side"])
                if aside==-wside:
                    watches.pop(s,None)
                    open_pos(s,aside,mark,t,"H1_CONFIRMED",anchor)
                    continue
                ctx=watch["context"]
                extreme=float(ctx.get("pullback_extreme") or watch["exit_price"])
                extreme=min(extreme,mark) if wside>0 else max(extreme,mark)
                ctx["pullback_extreme"]=extreme
                prof=flow_at(data[s]["buckets"],t,wside)
                if prof["counter_takeover"]:
                    ctx["counter_pressure_seen"]=True
                    ctx["phase"]="WAIT_RESUMPTION"
                    ctx["last_opposite_trade_epoch"]=prof["event_epoch"]
                opposite=ctx.get("last_opposite_trade_epoch")
                recovered=(wside*(mark/extreme-1.0)>=.0005) if extreme>0 else False
                ready=bool(ctx.get("phase")=="WAIT_RESUMPTION" and ctx.get("counter_pressure_seen") and
                           prof["resumed"] and recovered and opposite is not None and prof["event_epoch"]>opposite)
                if ready:
                    open_pos(s,wside,mark,t,"REENTRY",anchor,watch)
                continue

            # Exact dd97 initial entry semantics: confirmed H1 local is enough.
            if aside in (-1,1):
                open_pos(s,aside,mark,t,"H1_CONFIRMED",anchor)

        eq=mtm();peak=max(peak,eq)
        if peak>0:max_dd=max(max_dd,(peak-eq)/peak)
        if not equity_curve or t-equity_curve[-1][0]>=300:equity_curve.append((t,eq))

    final_equity=mtm()
    # Mark open positions but do not fabricate closes.
    open_pnl=sum(unrealized(p,last_price.get(s,p["entry"])) for s,p in positions.items())
    closed_pnl=sum(x["pnl"] for x in trades)
    wins=sum(1 for x in trades if x["pnl"]>0)
    reentries=[x for x in trades if x["entry_kind"]=="REENTRY"]
    result={
      "research_only":True,"source":"official_bybit_public_trade_archives","policy":"dd97_15s30s60s_counter_takeover_exhaustion_resumption",
      "start":start.isoformat(),"end_exclusive":end.isoformat(),"symbols":symbols,
      "starting_equity":500.0,"final_equity":final_equity,"return_pct":(final_equity/500.0-1)*100.0,
      "realized_pnl":closed_pnl,"gross_closed_pnl":sum(x["gross_pnl"] for x in trades),
      "fees_paid":sum(x["fees"] for x in trades),"open_pnl":open_pnl,"closed_trades":len(trades),"wins":wins,
      "avg_hold_seconds":sum(x["closed_t"]-x["opened_t"] for x in trades)/len(trades) if trades else None,
      "win_rate":wins/len(trades) if trades else None,"max_drawdown_pct":max_dd*100.0,
      "reentries_closed":len(reentries),"reentry_wins":sum(1 for x in reentries if x["pnl"]>0),
      "reentry_win_rate":sum(1 for x in reentries if x["pnl"]>0)/len(reentries) if reentries else None,
      "reentry_pnl":sum(x["pnl"] for x in reentries),
      "reentry_gross_pnl":sum(x["gross_pnl"] for x in reentries),
      "reentry_fees":sum(x["fees"] for x in reentries),
      "reentry_avg_hold_seconds":sum(x["closed_t"]-x["opened_t"] for x in reentries)/len(reentries) if reentries else None,
      "per_symbol":{s:{**stats[s],"win_rate":stats[s]["wins"]/stats[s]["trades"] if stats[s]["trades"] else None,
                        "reentry_win_rate":stats[s]["reentry_wins"]/stats[s]["reentries"] if stats[s]["reentries"] else None} for s in symbols},
      "open_positions":positions,"coverage":coverage,
      "best_reentries":sorted([{"symbol":x["symbol"],"pnl":x["pnl"],"side":x["side"],"opened_t":x["opened_t"],"closed_t":x["closed_t"],"reason":x["reason"]} for x in reentries],key=lambda x:x["pnl"],reverse=True)[:10],
      "worst_reentries":sorted([{"symbol":x["symbol"],"pnl":x["pnl"],"side":x["side"],"opened_t":x["opened_t"],"closed_t":x["closed_t"],"reason":x["reason"]} for x in reentries],key=lambda x:x["pnl"])[:10],
    }
    print("REENTRY_DD97_RESULT "+json.dumps(result,separators=(",",":"),default=str),flush=True)
    with open("reentry_dd97_result.json","w") as out:json.dump(result,out,indent=2,default=str)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",default="2026-10-29")
    ap.add_argument("--days",type=int,default=2)
    ap.add_argument("--symbols",nargs="+",default=["INIT","NEAR","GRASS","HYPE"])
    args=ap.parse_args()
    run(args.symbols,args.start,args.days)
