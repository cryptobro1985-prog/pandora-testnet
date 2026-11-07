#!/usr/bin/env python3
from __future__ import annotations

import argparse,bisect,gzip,hashlib,json,math,time
from pathlib import Path
from typing import Any
import requests

START_MS=1791072000000  # 2026-10-04T00:00:00Z
END_MS=1793664000000    # 2026-11-03T00:00:00Z
MINUTE=60_000
DEFAULT_PUBLICATION_LAG_MS=1_000
SOURCE_MAX_AGE_MS={"mark":2*MINUTE,"index":2*MINUTE,"oi":5*MINUTE,"funding":8*60*MINUTE}
AVAILABILITY_KEYS=("available_at_ms","received_at_ms","received_ts_ms")

def finite(v):
    return not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)

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

def last_at(rows,keys,t,completed_minute=False,*,publication_lag_ms=0,max_age_ms=None):
    """As-of join by physical completion plus an explicit publication assumption.

    A historical exchange timestamp is not a receive timestamp. For kline rows
    ts_ms is the *start*, whereas OI/funding rows are timestamped observations.
    Age is measured from physical completion/observation, before assumed lag.
    """
    if publication_lag_ms<0 or (max_age_ms is not None and max_age_ms<0):
        raise ValueError("lag and maximum age must be nonnegative")
    target=t-publication_lag_ms-(MINUTE if completed_minute else 0)
    i=bisect.bisect_right(keys,target)-1
    while i>=0:
        row=rows[i]
        effective_end=int(row["ts_ms"])+(MINUTE if completed_minute else 0)
        if max_age_ms is not None and t-effective_end>max_age_ms:return None
        # A source observation with a later receipt cannot enter this prefix;
        # an earlier, still-fresh and already received observation may be used.
        recorded=[int(row[k]) for k in AVAILABILITY_KEYS if row.get(k) is not None]
        if all(v<=t for v in recorded):return row
        i-=1
    return None

def at_or_before_offset(rows,keys,t,offset_ms):
    i=bisect.bisect_right(keys,t-offset_ms)-1
    return rows[i] if i>=0 else None

def stage_price(row):
    try:
        extreme=float(row["extreme_price"])
        retr=float((row.get("features") or {}).get("retrace_bps") or 0.0)/10000.0
        return extreme*(1+retr) if row["side"]=="LOW" else extreme*(1-retr)
    except Exception:return None

def enrich(infile:Path,outfile:Path,mark,index,oi,funding,*,publication_lag_ms=DEFAULT_PUBLICATION_LAG_MS):
    if infile.resolve()==outfile.resolve():raise ValueError("input history must not be overwritten")
    if publication_lag_ms<0:raise ValueError("publication lag must be nonnegative")
    for name,rows in (("mark",mark),("index",index),("oi",oi),("funding",funding)):
        if any(int(b["ts_ms"])<=int(a["ts_ms"]) for a,b in zip(rows,rows[1:])):
            raise ValueError(f"{name} source timestamps must be strictly increasing")
        fields=("open","high","low","close") if name in ("mark","index") else ("open_interest",) if name=="oi" else ("funding_rate",)
        if any(not finite(row.get(k)) for row in rows for k in fields):
            raise ValueError(f"{name} contains missing or nonfinite values")
        if name in ("mark","index") and any(row["low"]<=0 or row["low"]>min(row["open"],row["close"]) or row["high"]<max(row["open"],row["close"]) for row in rows):
            raise ValueError(f"{name} contains invalid OHLC")
        if name=="oi" and any(row["open_interest"]<0 for row in rows):raise ValueError("negative open interest")
    mk=[x["ts_ms"] for x in mark];ik=[x["ts_ms"] for x in index]
    ok=[x["ts_ms"] for x in oi];fk=[x["ts_ms"] for x in funding]
    counts={"rows":0,"mark":0,"index":0,"oi":0,"funding":0,"basis":0}
    with gzip.open(infile,"rt",encoding="utf-8") as src,gzip.open(outfile,"wt",encoding="utf-8",compresslevel=9) as dst:
        for line in src:
            if not line.strip():continue
            row=json.loads(line);t=int(row["snapshot_ts_ms"])
            # Re-enrichment must not retain values whose sources have become
            # unavailable under a more conservative lag/freshness policy.
            f={k:v for k,v in (row.get("features") or {}).items() if not k.startswith("hist_")}
            price=stage_price(row)
            def joined(name,rows,keys,at=t,minute=False):
                return last_at(rows,keys,at,completed_minute=minute,publication_lag_ms=publication_lag_ms,max_age_ms=SOURCE_MAX_AGE_MS[name])
            m=joined("mark",mark,mk,minute=True)
            ix=joined("index",index,ik,minute=True)
            o=joined("oi",oi,ok)
            fr=joined("funding",funding,fk)
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
                    # Anchor the change to the current *observation* rather
                    # than snapshot time: just after a publication lag the old
                    # implementation could compare a five-minute value to itself.
                    previous_t=int(o["ts_ms"])-sec*1000
                    prev=at_or_before_offset(oi,ok,int(o["ts_ms"]),sec*1000)
                    if prev and previous_t-int(prev["ts_ms"])>MINUTE:prev=None
                    if prev and any(int(prev[k])>t for k in AVAILABILITY_KEYS if prev.get(k) is not None):prev=None
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
                "causal_join":"physical completion + assumed publication lag <= snapshot; bounded source age",
                "publication_lag_ms":publication_lag_ms,
                "received_at_ms":None,
                "availability_assumed":True,
                "quality":"historical as-of approximation; receipt/publication latency unobserved",
                "upstream_snapshot_causality_verified":False,
            }
            for name,source,is_minute in (("mark",m,True),("index",ix,True),("oi",o,False),("funding",fr,False)):
                effective_end=int(source["ts_ms"])+(MINUTE if is_minute else 0) if source else None
                row["historical_gap_sources"][name]={
                    "source_ts_ms":source["ts_ms"] if source else None,
                    "effective_end_ms":effective_end,
                    "available_at_ms":max([effective_end+publication_lag_ms]+[int(source[k]) for k in AVAILABILITY_KEYS if source.get(k) is not None]) if source else None,
                    "received_at_ms":max([int(source[k]) for k in ("received_at_ms","received_ts_ms") if source.get(k) is not None],default=None) if source else None,
                    "age_ms":t-effective_end if source else None,
                    "max_age_ms":SOURCE_MAX_AGE_MS[name],
                    "availability":"assumed_historical" if source else "unavailable_or_stale",
                }
            dst.write(json.dumps(row,separators=(",",":"),ensure_ascii=False,allow_nan=False)+"\n")
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
    ap.add_argument("--publication-lag-ms",type=int,default=DEFAULT_PUBLICATION_LAG_MS,
                    help="unobserved historical publication latency assumption; never a measured receive time")
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
    coverage=enrich(src,enriched,mark,index,oi,funding,publication_lag_ms=args.publication_lag_ms)
    manifest={
        "version":"HYPE-LOCAL-HISTORICAL-GAPS-v2","symbol":"HYPEUSDT",
        "period":["2026-10-04T00:00:00Z","2026-11-03T00:00:00Z"],
        "sources":{
            "mark":"Bybit /v5/market/mark-price-kline 1m",
            "index":"Bybit /v5/market/index-price-kline 1m",
            "open_interest":"Bybit /v5/market/open-interest 5min",
            "funding":"Bybit /v5/market/funding/history",
        },
        "counts":{"mark":len(mark),"index":len(index),"oi":len(oi),"funding":len(funding)},
        "snapshot_coverage":coverage,
        "join_rule":"physical completion + assumed publication lag <= snapshot; stale sources excluded",
        "publication_lag_ms":args.publication_lag_ms,
        "source_max_age_ms":SOURCE_MAX_AGE_MS,
        "historical_receive_timestamps_available":False,
        "download_completed_at_ms":int(time.time()*1000),
        "limitation":"publication lag is a sensitivity assumption, not proof of actual historical availability; source input snapshots must also pass an independent causal audit",
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
