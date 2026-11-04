#!/usr/bin/env python3
"""Research-only companion capture for HYPE local analysis.

Captures causal M1/M3/M5/H1 context plus low-frequency public positioning and
clock/instrument metadata. No private endpoints, no orders, no production writes.
"""
from __future__ import annotations
import argparse, json, math, time
from pathlib import Path
from typing import Any
import requests

BASES=("https://api.bybit.com","https://api.bytick.com","https://api.bybit.kz","https://api.bybit.ae","https://api.bybit.eu")
SYMBOL="HYPEUSDT"

def request_json(path:str,params:dict[str,Any]|None=None)->dict[str,Any]:
    last=None
    for base in BASES:
        try:
            r=requests.get(base+path,params=params or {},timeout=10); r.raise_for_status(); obj=r.json()
            if obj.get("retCode") not in (0,None): raise RuntimeError(f"Bybit error {obj.get('retCode')}: {obj.get('retMsg')}")
            return obj
        except Exception as exc: last=exc
    raise RuntimeError(f"all Bybit REST endpoints failed: {last}")

def fetch_klines(interval:str,limit:int):
    obj=request_json("/v5/market/kline",{"category":"linear","symbol":SYMBOL,"interval":interval,"limit":limit}); rows=[]
    for r in reversed(obj.get("result",{}).get("list",[])):
        if len(r)<7: continue
        rows.append({"start_ms":int(r[0]),"open":float(r[1]),"high":float(r[2]),"low":float(r[3]),
                     "close":float(r[4]),"volume":float(r[5]),"turnover":float(r[6]),"interval":interval})
    return rows

def fetch_ticker():
    obj=request_json("/v5/market/tickers",{"category":"linear","symbol":SYMBOL})
    rows=obj.get("result",{}).get("list",[]); return rows[0] if rows else {}

def fetch_server_time():
    obj=request_json("/v5/market/time"); return {"api_time_ms":obj.get("time"),"result":obj.get("result",{})}

def fetch_instrument():
    obj=request_json("/v5/market/instruments-info",{"category":"linear","symbol":SYMBOL})
    rows=obj.get("result",{}).get("list",[]); return rows[0] if rows else {}

def fetch_account_ratio():
    obj=request_json("/v5/market/account-ratio",{"category":"linear","symbol":SYMBOL,"period":"5min","limit":1})
    rows=obj.get("result",{}).get("list",[]); return rows[0] if rows else {}

def safe(call):
    try: return {"ok":True,"value":call()}
    except Exception as exc: return {"ok":False,"error":repr(exc)}

def num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None

def structural_snapshot(candles,ticker,server_time=None,account_ratio=None):
    m1=candles.get("1",[]); h1=candles.get("60",[])
    def bounds(rows,n):
        z=rows[-n:] if n and len(rows)>=n else rows
        return (None,None) if not z else (min(x["low"] for x in z),max(x["high"] for x in z))
    lo60,hi60=bounds(m1,60); lo360,hi360=bounds(m1,360); lo24,hi24=bounds(h1,24)
    last=m1[-1] if m1 else {}; lastp=num(ticker.get("lastPrice")); mark=num(ticker.get("markPrice"))
    index=num(ticker.get("indexPrice")); oi=num(ticker.get("openInterest"))
    bybit_ms=num((server_time or {}).get("api_time_ms")); now_ms=int(time.time()*1000)
    buy=num((account_ratio or {}).get("buyRatio")); sell=num((account_ratio or {}).get("sellRatio"))
    return {"ts_ms":now_ms,"symbol":SYMBOL,"last_m1":last,
            "rolling_60m_low":lo60,"rolling_60m_high":hi60,
            "rolling_6h_low":lo360,"rolling_6h_high":hi360,
            "rolling_24h_low":lo24,"rolling_24h_high":hi24,
            "last_price":lastp,"mark_price":mark,"index_price":index,
            "basis_bps":None if not mark or not index else (mark/index-1)*10000,
            "open_interest":oi,"oi_notional":None if oi is None or lastp is None else oi*lastp,
            "funding_rate":num(ticker.get("fundingRate")),
            "turnover_24h":num(ticker.get("turnover24h")),"volume_24h":num(ticker.get("volume24h")),
            "bybit_server_time_ms":bybit_ms,
            "runner_clock_offset_ms":None if bybit_ms is None else now_ms-bybit_ms,
            "long_holder_ratio":buy,"short_holder_ratio":sell,
            "long_short_holder_ratio":None if buy is None or sell in (None,0) else buy/sell}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--minutes",type=int,required=True)
    ap.add_argument("--output",type=Path,required=True); ap.add_argument("--poll-seconds",type=int,default=60)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    raw=(args.output/"HYPE_market_context.jsonl").open("a",encoding="utf-8")
    state=(args.output/"HYPE_structural_context_1m.jsonl").open("a",encoding="utf-8")
    start=time.time(); end=start+args.minutes*60; polls=errors=0; first=True; last_error=None
    instrument=safe(fetch_instrument); last_ratio={}; ratio_poll=-999
    try:
        while time.time()<end:
            t0=time.time()
            try:
                limits={"1":480 if first else 8,"3":240 if first else 8,"5":180 if first else 8,"60":72 if first else 4}
                candles={k:fetch_klines(k,v) for k,v in limits.items()}; ticker=fetch_ticker(); server=safe(fetch_server_time)
                if polls-ratio_poll>=5 or first:
                    rr=safe(fetch_account_ratio); ratio_poll=polls
                    if rr.get("ok"): last_ratio=rr.get("value") or {}
                record={"received_ts_ms":int(time.time()*1000),"symbol":SYMBOL,"initial_backfill":first,
                        "candles":candles,"ticker":ticker,"server_time":server,
                        "instrument":instrument if first else None,"account_ratio":last_ratio}
                raw.write(json.dumps(record,separators=(",",":"))+"\n"); raw.flush()
                state.write(json.dumps(structural_snapshot(candles,ticker,server.get("value") if server.get("ok") else None,last_ratio),separators=(",",":"))+"\n"); state.flush()
                polls+=1; first=False
            except Exception as exc:
                errors+=1; last_error=repr(exc)
                state.write(json.dumps({"ts_ms":int(time.time()*1000),"error":last_error},separators=(",",":"))+"\n"); state.flush()
            time.sleep(min(max(1.0,args.poll_seconds-(time.time()-t0)),max(0.0,end-time.time())))
    finally:
        raw.close(); state.close()
    summary={"research_only":True,"symbol":SYMBOL,"minutes_requested":args.minutes,
             "started_ts_ms":int(start*1000),"ended_ts_ms":int(time.time()*1000),
             "poll_seconds":args.poll_seconds,"successful_polls":polls,"errors":errors,"last_error":last_error,
             "captured_intervals":["1","3","5","60"],
             "initial_history":{"M1":480,"M3":240,"M5":180,"H1":72},
             "extra_public_context":["Bybit server time / runner clock offset","instrument metadata",
                                     "5m long-short holder ratio","mark-index basis","OI notional"],
             "purpose":"causal HYPE v6 context; no trading"}
    (args.output/"CONTEXT_SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print("CONTEXT_SUMMARY "+json.dumps(summary),flush=True)

if __name__=="__main__": main()
