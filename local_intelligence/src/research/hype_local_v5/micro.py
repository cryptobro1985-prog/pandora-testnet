#!/usr/bin/env python3
"""Aggregate HYPEUSDT Bybit public trade archives into causal 5-second microstructure bars.

Research only. No order placement.
"""
from __future__ import annotations
import argparse, csv, datetime as dt, gzip, io, json
from pathlib import Path
import requests

SYMBOL="HYPEUSDT"
UA="pandora-hype-local-v5-micro/1.0"

def d(s): return dt.datetime.strptime(s,"%Y-%m-%d").date()

def agg_day(day, out):
    url=f"https://public.bybit.com/trading/{SYMBOL}/{SYMBOL}{day.isoformat()}.csv.gz"
    r=requests.get(url,stream=True,timeout=90,headers={"User-Agent":UA})
    if r.status_code==404:
        print("404",day,flush=True); return 0
    r.raise_for_status()
    n=0
    prev_side=None
    # streaks are local to bucket; reset when bucket changes
    bucket_state={}
    try:
        gz=gzip.GzipFile(fileobj=r.raw)
        txt=io.TextIOWrapper(gz,encoding="utf-8",newline="")
        reader=csv.DictReader(txt)
        for row in reader:
            try:
                tr=float(row.get("timestamp") or row.get("time") or row.get("execTime"))
                tms=int(tr if tr>1e12 else tr*1000)
                b=(tms//5000)*5000
                side=(row.get("side") or "").lower()
                px=float(row.get("price") or 0)
                qty=float(row.get("size") or row.get("qty") or 0)
                notion=px*qty
                z=out.get(b)
                if z is None:
                    z={
                        "ts_ms":b,"open":px,"high":px,"low":px,"close":px,
                        "buy_notional":0.0,"sell_notional":0.0,
                        "buy_qty":0.0,"sell_qty":0.0,
                        "buy_count":0,"sell_count":0,"trade_count":0,
                        "max_trade_notional":0.0,
                        "large10_buy":0.0,"large10_sell":0.0,
                        "large25_buy":0.0,"large25_sell":0.0,
                        "large50_buy":0.0,"large50_sell":0.0,
                        "large10_buy_count":0,"large10_sell_count":0,
                        "side_switches":0,"max_buy_streak":0,"max_sell_streak":0,
                        "_last_side":"","_buy_streak":0,"_sell_streak":0,
                        "first_trade_ms":tms,"last_trade_ms":tms,
                    }
                    out[b]=z
                z["high"]=max(z["high"],px); z["low"]=min(z["low"],px); z["close"]=px
                z["max_trade_notional"]=max(z["max_trade_notional"],notion)
                z["trade_count"]+=1; z["last_trade_ms"]=tms
                if z["_last_side"] and z["_last_side"]!=side: z["side_switches"]+=1
                z["_last_side"]=side
                if side=="buy":
                    z["buy_notional"]+=notion; z["buy_qty"]+=qty; z["buy_count"]+=1
                    z["_buy_streak"]+=1; z["_sell_streak"]=0
                    z["max_buy_streak"]=max(z["max_buy_streak"],z["_buy_streak"])
                    if notion>=10000: z["large10_buy"]+=notion; z["large10_buy_count"]+=1
                    if notion>=25000: z["large25_buy"]+=notion
                    if notion>=50000: z["large50_buy"]+=notion
                elif side=="sell":
                    z["sell_notional"]+=notion; z["sell_qty"]+=qty; z["sell_count"]+=1
                    z["_sell_streak"]+=1; z["_buy_streak"]=0
                    z["max_sell_streak"]=max(z["max_sell_streak"],z["_sell_streak"])
                    if notion>=10000: z["large10_sell"]+=notion; z["large10_sell_count"]+=1
                    if notion>=25000: z["large25_sell"]+=notion
                    if notion>=50000: z["large50_sell"]+=notion
                n+=1
            except Exception:
                continue
    finally:
        r.close()
    return n

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",required=True); ap.add_argument("--end",required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    out={}; raw=0; day=d(a.start); end=d(a.end)
    while day<=end:
        n=agg_day(day,out); raw+=n
        print(day,"raw",n,"bars5s",len(out),flush=True)
        day+=dt.timedelta(days=1)
    rows=[]
    for k in sorted(out):
        z=out[k]
        for q in ["_last_side","_buy_streak","_sell_streak"]: z.pop(q,None)
        den=z["buy_notional"]+z["sell_notional"]
        z["flow_imbalance"]=0.0 if not den else (z["buy_notional"]-z["sell_notional"])/den
        cden=z["buy_count"]+z["sell_count"]
        z["trade_imbalance"]=0.0 if not cden else (z["buy_count"]-z["sell_count"])/cden
        elapsed=max(1,(z["last_trade_ms"]-z["first_trade_ms"])/1000)
        z["trades_per_second"]=z["trade_count"]/elapsed
        rows.append(z)
    path=a.output/f"HYPE_micro5s_{a.start}_{a.end}.csv.gz"
    if rows:
        keys=list(rows[0])
        with gzip.open(path,"wt",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)
    summary={"symbol":SYMBOL,"start":a.start,"end":a.end,"raw_trades":raw,"bars5s":len(rows),
             "features":["aggressive notional/qty/count","large-trade tiers 10k/25k/50k",
                         "side switches","max same-side streak","trade arrival velocity","execution OHLC"]}
    (a.output/"SUMMARY.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print("SUMMARY",json.dumps(summary),flush=True)

if __name__=="__main__": main()
