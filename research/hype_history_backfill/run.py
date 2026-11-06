#!/usr/bin/env python3
from __future__ import annotations

import argparse,bisect,gzip,hashlib,json,math,time
from pathlib import Path
from typing import Any
import requests

START_MS=1791072000000  # 2026-10-04T00:00:00Z
END_MS=1793664000000    # 2026-11-03T00:00:00Z
MINUTE=60_000

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def get_json(session,url,params,retries=6):
    last=None
    for i in range(retries):
        try:
            r=session.get(url,params=params,timeout=30)
            r.raise_for_status()
            obj=r.json()
            if not obj.get("ok"):raise RuntimeError(obj.get("error") or "relay returned ok=false")
            return obj
        except Exception as exc:
            last=exc;time.sleep(min(8,0.5*(2**i)))
    raise RuntimeError(f"relay request failed: {last}")

def fetch_klines(session,relay,kind):
    rows={}
    # 900 minutes leaves margin below the 1000-row API limit.
    step=900*MINUTE
    cur=START_MS
    while cur<END_MS:
        end=min(END_MS-1,cur+step-1)
        obj=get_json(session,relay,{"kind":kind,"start":cur,"end":end,"interval":"1","limit":1000})
        for r in obj.get("rows") or []:
            if len(r)>=5:
                ts=int(r[0])
                if START_MS<=ts<END_MS:
                    rows[ts]={"ts_ms":ts,"open":float(r[1]),"high":float(r[2]),
                              "low":float(r[3]),"close":float(r[4])}
        cur=end+1
        print(json.dumps({"kind":kind,"rows":len(rows),"through_ms":cur}),flush=True)
    return [rows[k] for k in sorted(rows)]

def fetch_oi(session,relay):
    rows={}
    # Small chunks plus cursor pagination make the 200-row limit deterministic.
    step=24*60*MINUTE
    cur=START_MS
    while cur<END_MS:
        end=min(END_MS-1,cur+step-1);cursor="";seen=set()
        while True:
            params={"kind":"oi","start":cur,"end":end,"interval":"5min","limit":200}
            if cursor:params["cursor"]=cursor
            obj=get_json(session,relay,params)
            for r in obj.get("rows") or []:
                try:
                    ts=int(r["timestamp"]);v=float(r["openInterest"])
                except Exception:continue
                if START_MS<=ts<END_MS:rows[ts]={"ts_ms":ts,"open_interest":v}
            nxt=str(obj.get("next_cursor") or "")
            if not nxt or nxt in seen:break
            seen.add(nxt);cursor=nxt
        cur=end+1
        print(json.dumps({"kind":"oi","rows":len(rows),"through_ms":cur}),flush=True)
    return [rows[k] for k in sorted(rows)]

def fetch_funding(session,relay):
    obj=get_json(session,relay,{"kind":"funding","start":START_MS,"end":END_MS-1,"limit":200})
    rows={}
    for r in obj.get("rows") or []:
        try:
            ts=int(r["fundingRateTimestamp"]);v=float(r["fundingRate"])
        except Exception:continue
        if START_MS<=ts<END_MS:rows[ts]={"ts_ms":ts,"funding_rate":v}
    return [rows[k] for k in sorted(rows)]

def last_at(rows,keys,t,completed_minute=False):
    target=t-MINUTE if completed_minute else t
    i=bisect.bisect_right(keys,target)-1
    return rows[i] if i>=0 else None

def at_or_before_offset(rows,keys,t,offset_ms):
    i=bisect.bisect_right(keys,t-offset_ms)-1
    return rows[i] if i>=0 else None

def stage_price(row):
    try:
        extreme=float(row["extreme_price"])
        retr=float((row.get("features") or {}).get("retrace_bps") or 0.0)/10000.0
        return extreme*(1+retr) if row["side"]=="LOW" else extreme*(1-retr)
    except Exception:return None

def enrich(infile:Path,outfile:Path,mark,index,oi,funding):
    mk=[x["ts_ms"] for x in mark];ik=[x["ts_ms"] for x in index]
    ok=[x["ts_ms"] for x in oi];fk=[x["ts_ms"] for x in funding]
    counts={"rows":0,"mark":0,"index":0,"oi":0,"funding":0,"basis":0}
    with gzip.open(infile,"rt",encoding="utf-8") as src,gzip.open(outfile,"wt",encoding="utf-8",compresslevel=9) as dst:
        for line in src:
            if not line.strip():continue
            row=json.loads(line);t=int(row["snapshot_ts_ms"]);f=dict(row.get("features") or {})
            price=stage_price(row)
            m=last_at(mark,mk,t,completed_minute=True)
            ix=last_at(index,ik,t,completed_minute=True)
            o=last_at(oi,ok,t)
            fr=last_at(funding,fk,t)
            if m:
                f["hist_mark_available"]=1.0
                if price and price>0:f["hist_mark_price_rel"]=m["close"]/price-1.0
                counts["mark"]+=1
            if ix:
                f["hist_index_available"]=1.0
                if price and price>0:f["hist_index_price_rel"]=ix["close"]/price-1.0
                counts["index"]+=1
            if m and ix and ix["close"]:
                f["hist_basis_bps"]=(m["close"]/ix["close"]-1.0)*10000.0
                counts["basis"]+=1
            if o and o["open_interest"]>=0:
                ov=float(o["open_interest"]);f["hist_oi_available"]=1.0
                f["hist_open_interest_log"]=math.log1p(ov)
                if price and price>0:f["hist_oi_notional_log"]=math.log1p(ov*price)
                for sec in (300,3600):
                    prev=at_or_before_offset(oi,ok,t,sec*1000)
                    if prev and float(prev["open_interest"])>0:
                        f[f"hist_oi_delta_{sec}s"]=ov/float(prev["open_interest"])-1.0
                counts["oi"]+=1
            if fr:
                f["hist_funding_available"]=1.0;f["hist_funding_rate"]=float(fr["funding_rate"])
                counts["funding"]+=1
            row["features"]={k:float(v) for k,v in f.items() if finite(v)}
            row["historical_gap_sources"]={
                "mark_ts_ms":m["ts_ms"] if m else None,"index_ts_ms":ix["ts_ms"] if ix else None,
                "oi_ts_ms":o["ts_ms"] if o else None,"funding_ts_ms":fr["ts_ms"] if fr else None,
                "causal_join":"latest available at/before snapshot; mark/index require completed 1m bar",
            }
            dst.write(json.dumps(row,separators=(",",":"),ensure_ascii=False)+"\n")
            counts["rows"]+=1
    return counts

def write_json_gz(path,rows):
    with gzip.open(path,"wt",encoding="utf-8",compresslevel=9) as f:
        for row in rows:f.write(json.dumps(row,separators=(",",":"))+"\n")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--relay",required=True)
    ap.add_argument("--history-dir",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    src=args.history_dir/"candidate_snapshots.jsonl.gz"
    if not src.exists():raise SystemExit(f"missing {src}")
    relay=args.relay.rstrip("/")+"/hype-history-page"
    session=requests.Session();session.headers.update({"User-Agent":"PANDORA-Local-History-Gap/1.0"})
    mark=fetch_klines(session,relay,"mark")
    index=fetch_klines(session,relay,"index")
    oi=fetch_oi(session,relay)
    funding=fetch_funding(session,relay)
    for name,rows in (("mark_1m",mark),("index_1m",index),("open_interest_5m",oi),("funding",funding)):
        write_json_gz(args.output/(name+".jsonl.gz"),rows)
    enriched=args.output/"candidate_snapshots_enriched.jsonl.gz"
    coverage=enrich(src,enriched,mark,index,oi,funding)
    manifest={
        "version":"HYPE-LOCAL-HISTORICAL-GAPS-v1","symbol":"HYPEUSDT",
        "period":["2026-10-04T00:00:00Z","2026-11-03T00:00:00Z"],
        "sources":{
            "mark":"Bybit /v5/market/mark-price-kline 1m",
            "index":"Bybit /v5/market/index-price-kline 1m",
            "open_interest":"Bybit /v5/market/open-interest 5min",
            "funding":"Bybit /v5/market/funding/history",
        },
        "counts":{"mark":len(mark),"index":len(index),"oi":len(oi),"funding":len(funding)},
        "snapshot_coverage":coverage,
        "join_rule":"only source timestamp <= snapshot; mark/index use last fully completed 1m bar",
        "never_synthesized":["historical L50 replay","historical liquidation websocket events",
                             "historical receive timestamps/latency","historical websocket sequence health"],
        "files":{},
    }
    for p in sorted(args.output.iterdir()):
        if p.is_file() and p.name!="manifest.json":
            manifest["files"][p.name]={"bytes":p.stat().st_size,"sha256":sha256(p)}
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print("HISTORY_GAP_BACKFILL="+json.dumps({"counts":manifest["counts"],"coverage":coverage},separators=(",",":")))

if __name__=="__main__":main()
