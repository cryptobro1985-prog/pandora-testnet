#!/usr/bin/env python3
"""Research-only companion context capture for HYPE.

Primary fast market data (trades/L50/liquidations/ticker/klines) is captured on
Bybit public websocket by research.py. This companion adds REST-only public
metadata (instrument contract + 5m long/short ratio + server time), preferably
through an optional relay outside GitHub's blocked region.

No private endpoints, no API key, no orders.
"""
from __future__ import annotations
import argparse, json, math, os, time
from pathlib import Path
from typing import Any
import requests

BASES=("https://api.bybit.com","https://api.bytick.com","https://api.bybit.kz","https://api.bybit.ae","https://api.bybit.eu")
SYMBOL="HYPEUSDT"
RELAY_URL=os.getenv("HYPE_REST_RELAY_URL","").strip().rstrip("/")
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"PANDORA-HYPE-Research/1.0","Accept":"application/json"})

def request_json(path:str,params:dict[str,Any]|None=None)->dict[str,Any]:
    last=None
    for base in BASES:
        try:
            r=SESSION.get(base+path,params=params or {},timeout=8)
            r.raise_for_status()
            obj=r.json()
            if obj.get("retCode") not in (0,None):
                raise RuntimeError(f"Bybit error {obj.get('retCode')}: {obj.get('retMsg')}")
            obj["_base"]=base
            return obj
        except Exception as exc:
            last=exc
    raise RuntimeError(f"all Bybit REST endpoints failed: {last}")

def fetch_relay()->dict[str,Any]:
    if not RELAY_URL:
        raise RuntimeError("HYPE_REST_RELAY_URL not set")
    r=SESSION.get(RELAY_URL+"/hype-context",timeout=10)
    r.raise_for_status()
    obj=r.json()
    if obj.get("error"):
        raise RuntimeError(obj["error"])
    return obj

def fetch_klines(interval:str,limit:int):
    obj=request_json("/v5/market/kline",{"category":"linear","symbol":SYMBOL,"interval":interval,"limit":limit})
    rows=[]
    for r in reversed(obj.get("result",{}).get("list",[])):
        if len(r)<7: continue
        rows.append({"start_ms":int(r[0]),"open":float(r[1]),"high":float(r[2]),"low":float(r[3]),
                     "close":float(r[4]),"volume":float(r[5]),"turnover":float(r[6]),"interval":interval})
    return rows

def fetch_ticker():
    obj=request_json("/v5/market/tickers",{"category":"linear","symbol":SYMBOL})
    rows=obj.get("result",{}).get("list",[])
    return rows[0] if rows else {}

def fetch_server_time():
    obj=request_json("/v5/market/time")
    return {"api_time_ms":obj.get("time"),"result":obj.get("result",{}),"base":obj.get("_base")}

def fetch_instrument():
    obj=request_json("/v5/market/instruments-info",{"category":"linear","symbol":SYMBOL})
    rows=obj.get("result",{}).get("list",[])
    return rows[0] if rows else {}

def fetch_account_ratio():
    obj=request_json("/v5/market/account-ratio",{"category":"linear","symbol":SYMBOL,"period":"5min","limit":1})
    rows=obj.get("result",{}).get("list",[])
    return rows[0] if rows else {}

def safe(call):
    try:
        return {"ok":True,"value":call()}
    except Exception as exc:
        return {"ok":False,"error":repr(exc)}

def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def structural_snapshot(candles,ticker,server_time=None,account_ratio=None):
    m1=candles.get("1",[]); h1=candles.get("60",[])
    def bounds(rows,n):
        z=rows[-n:] if n and len(rows)>=n else rows
        return (None,None) if not z else (min(x["low"] for x in z),max(x["high"] for x in z))
    lo60,hi60=bounds(m1,60); lo360,hi360=bounds(m1,360); lo24,hi24=bounds(h1,24)
    last=m1[-1] if m1 else {}
    lastp=num(ticker.get("lastPrice")); mark=num(ticker.get("markPrice"))
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
    ap=argparse.ArgumentParser()
    ap.add_argument("--minutes",type=int,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--poll-seconds",type=int,default=60)
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    raw=(args.output/"HYPE_market_context.jsonl").open("a",encoding="utf-8")
    state=(args.output/"HYPE_structural_context_1m.jsonl").open("a",encoding="utf-8")
    start=time.time();end=start+args.minutes*60
    polls=errors=0;first=True;last_error=None
    source_ok={"relay":0,"direct_rest":0,"websocket_primary_note":0}
    instrument={};last_ratio={};last_server={}
    ratio_poll=-999
    try:
        while time.time()<end:
            t0=time.time();now_ms=int(t0*1000)
            row_errors=[]
            # REST-only fields: relay first, direct REST second.
            relay=safe(fetch_relay) if RELAY_URL else {"ok":False,"error":"relay_not_configured"}
            if relay.get("ok"):
                rv=relay["value"]
                instrument=rv.get("instrument") or instrument
                last_ratio=rv.get("account_ratio") or last_ratio
                last_server=rv.get("server_time") or last_server
                source_ok["relay"]+=1
            else:
                if first or not instrument:
                    x=safe(fetch_instrument)
                    if x.get("ok"): instrument=x["value"];source_ok["direct_rest"]+=1
                    else: row_errors.append("instrument:"+x["error"])
                if polls-ratio_poll>=5 or first:
                    x=safe(fetch_account_ratio);ratio_poll=polls
                    if x.get("ok"): last_ratio=x["value"] or last_ratio;source_ok["direct_rest"]+=1
                    else: row_errors.append("account_ratio:"+x["error"])
                x=safe(fetch_server_time)
                if x.get("ok"): last_server=x["value"];source_ok["direct_rest"]+=1
                else: row_errors.append("server_time:"+x["error"])

            # Optional REST redundancy only. Primary ticker+M1/M3/M5/H1 are raw WS.
            ticker={}
            candles={}
            xt=safe(fetch_ticker)
            if xt.get("ok"):
                ticker=xt["value"];source_ok["direct_rest"]+=1
            else:
                row_errors.append("ticker_rest_optional:"+xt["error"])
            limits={"1":480 if first else 8,"3":240 if first else 8,"5":180 if first else 8,"60":72 if first else 4}
            for k,v in limits.items():
                x=safe(lambda k=k,v=v:fetch_klines(k,v))
                if x.get("ok"):
                    candles[k]=x["value"];source_ok["direct_rest"]+=1
                else:
                    candles[k]=[];row_errors.append(f"kline_{k}_rest_optional:"+x["error"])

            record={"received_ts_ms":now_ms,"symbol":SYMBOL,"initial_backfill":first,
                    "candles":candles,"ticker":ticker,
                    "server_time":{"ok":bool(last_server),"value":last_server},
                    "instrument":{"ok":bool(instrument),"value":instrument} if first else None,
                    "account_ratio":last_ratio,
                    "rest_relay_configured":bool(RELAY_URL),
                    "primary_market_source":"Bybit public websocket",
                    "rest_only_complete":bool(instrument and last_ratio and last_server),
                    "errors":row_errors}
            raw.write(json.dumps(record,separators=(",",":"))+"\n");raw.flush()
            snap=structural_snapshot(candles,ticker,last_server,last_ratio)
            snap["rest_only_complete"]=record["rest_only_complete"]
            snap["rest_relay_configured"]=bool(RELAY_URL)
            snap["errors"]=row_errors
            state.write(json.dumps(snap,separators=(",",":"))+"\n");state.flush()
            polls+=1;first=False
            if row_errors: errors+=1;last_error="; ".join(row_errors[-3:])
            time.sleep(min(max(1.0,args.poll_seconds-(time.time()-t0)),max(0.0,end-time.time())))
    finally:
        raw.close();state.close()
    summary={"research_only":True,"symbol":SYMBOL,"minutes_requested":args.minutes,
             "started_ts_ms":int(start*1000),"ended_ts_ms":int(time.time()*1000),
             "poll_seconds":args.poll_seconds,"successful_polls":polls,"polls_with_any_error":errors,
             "last_error":last_error,"relay_configured":bool(RELAY_URL),"source_success_counts":source_ok,
             "primary_websocket_context":["publicTrade","orderbook.50","allLiquidation","tickers","kline.1","kline.3","kline.5","kline.60"],
             "rest_only_context":["server time / runner clock offset","instrument metadata","5m long-short holder ratio"],
             "purpose":"causal HYPE context; no trading"}
    (args.output/"CONTEXT_SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print("CONTEXT_SUMMARY "+json.dumps(summary),flush=True)

if __name__=="__main__":
    main()
