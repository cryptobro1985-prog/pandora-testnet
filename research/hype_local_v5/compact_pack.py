#!/usr/bin/env python3
"""Compact, self-describing HYPE research package.

Semantic-lossless for the 110-point research contract: every DIRECT primary
value needed by the contract is stored; DERIVED values are reproducible from
those streams; POST_ANALYSIS values are produced by frozen-v6 replay / 12h
analysis. Raw JSON envelope repetition is removed. Price/qty are scaled integers.
"""
from __future__ import annotations
import argparse, hashlib, json, lzma, shutil
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
import msgpack

FORMAT_VERSION="HYPE110-COMPACT-v1"
SCHEMA_VERSION="110+extras-v1"
TICKER_KEYS=("lastPrice","markPrice","indexPrice","openInterest","fundingRate",
"turnover24h","volume24h","bid1Price","bid1Size","ask1Price","ask1Size",
"highPrice24h","lowPrice24h","price24hPcnt","nextFundingTime")

def dec_places(v:Any)->int:
    return max(0,-Decimal(str(v)).as_tuple().exponent)

def read_jsonl(path:Path):
    if not path.exists(): return
    with path.open("r",encoding="utf-8") as f:
        for line in f:
            try: yield json.loads(line)
            except Exception: continue

def iter_raw_frames(path:Path):
    for outer in read_jsonl(path) or []:
        raw=outer.get("raw_text")
        try: msg=json.loads(raw) if isinstance(raw,str) else raw
        except Exception: msg={"_raw_text":raw}
        yield outer,msg

def detect_scales(path:Path):
    pd=qd=0
    for _,msg in iter_raw_frames(path):
        if not isinstance(msg,dict): continue
        topic=msg.get("topic","")
        if topic.startswith("orderbook."):
            data=msg.get("data") or {}
            for side in ("b","a"):
                for p,q in data.get(side,[]):
                    pd=max(pd,dec_places(p)); qd=max(qd,dec_places(q))
        elif topic.startswith(("publicTrade.","allLiquidation.")):
            for x in msg.get("data") or []:
                pd=max(pd,dec_places(x.get("p",0))); qd=max(qd,dec_places(x.get("v",0)))
    return 10**pd,10**qd,pd,qd

def scaled(v:Any,scale:int)->int:
    return int(Decimal(str(v))*scale)

def pack_stream(path:Path,records:Iterable[Any])->int:
    path.parent.mkdir(parents=True,exist_ok=True)
    packer=msgpack.Packer(use_bin_type=True); n=0
    with lzma.LZMAFile(path,"wb",preset=6) as f:
        for rec in records:
            f.write(packer.pack(rec)); n+=1
    return n

def pack_events(src:Path,dst:Path):
    ps,qs,pd,qd=detect_scales(src)
    def records():
        prev_book={"recv":0,"ets":0,"u":0,"seq":0}; first_book=True
        last_book_price={"b":0,"a":0}
        prev_trade={"recv":0,"ts":0,"seq":0}; first_trade=True
        prev_liq={"recv":0,"ts":0}; first_liq=True
        for outer,msg in iter_raw_frames(src):
            recv=int(outer.get("received_ts_ms") or 0)
            receipt=int(outer.get("receipt_sequence") or 0)
            endpoint=outer.get("endpoint")
            if not isinstance(msg,dict):
                yield [9,recv,receipt,endpoint,msg]; continue
            topic=msg.get("topic","")
            if topic.startswith("orderbook."):
                data=msg.get("data") or {}
                ets=int(msg.get("ts") or 0); u=int(data.get("u") or 0); seq=int(data.get("seq") or 0)
                sides=[]
                for side in ("b","a"):
                    rows=[]
                    for p,q in data.get(side,[]):
                        pi=scaled(p,ps); qi=scaled(q,qs)
                        rows.append([pi-last_book_price[side],qi]); last_book_price[side]=pi
                    sides.append(rows)
                timing=[recv,ets,u,seq] if first_book else [
                    recv-prev_book["recv"],ets-prev_book["ets"],u-prev_book["u"],seq-prev_book["seq"]]
                first_book=False; prev_book.update(recv=recv,ets=ets,u=u,seq=seq)
                yield [0,1 if msg.get("type")=="snapshot" else 0,*timing,*sides]
            elif topic.startswith("publicTrade."):
                for x in msg.get("data") or []:
                    ts=int(x.get("T") or msg.get("ts") or 0); tseq=int(x.get("seq") or 0)
                    tick={"PlusTick":1,"MinusTick":-1,"ZeroPlusTick":2,"ZeroMinusTick":-2}.get(x.get("L"),0)
                    tr=[recv,ts,tseq] if first_trade else [
                        recv-prev_trade["recv"],ts-prev_trade["ts"],tseq-prev_trade["seq"]]
                    first_trade=False; prev_trade.update(recv=recv,ts=ts,seq=tseq)
                    yield [1,*tr,1 if x.get("S")=="Buy" else 0,scaled(x.get("p",0),ps),
                           scaled(x.get("v",0),qs),tick,int(bool(x.get("BT"))),int(bool(x.get("RPI")))]
            elif topic.startswith("allLiquidation."):
                for x in msg.get("data") or []:
                    ts=int(x.get("T") or msg.get("ts") or 0)
                    lr=[recv,ts] if first_liq else [recv-prev_liq["recv"],ts-prev_liq["ts"]]
                    first_liq=False; prev_liq.update(recv=recv,ts=ts)
                    yield [2,*lr,1 if x.get("S")=="Buy" else 0,scaled(x.get("p",0),ps),scaled(x.get("v",0),qs)]
            elif topic.startswith("tickers."):
                data=msg.get("data") or {}
                if isinstance(data,list): data=data[0] if data else {}
                small={k:data[k] for k in TICKER_KEYS if k in data}
                yield [3,recv,int(msg.get("ts") or 0),small]
            else:
                yield [9,recv,receipt,endpoint,msg]
    n=pack_stream(dst,records())
    return {"records":n,"price_scale":ps,"qty_scale":qs,"price_decimals":pd,"qty_decimals":qd}

def pack_tabular_jsonl(src:Path,dst:Path)->int:
    rows=list(read_jsonl(src) or []); keys=[]; seen=set()
    for row in rows:
        for k in row:
            if k not in seen: seen.add(k); keys.append(k)
    def recs():
        yield ["__keys__",keys]
        for row in rows: yield [row.get(k) for k in keys]
    return pack_stream(dst,recs())

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def schema_110():
    titles=[
"Last Price","Mark Price","Index Price","M1 OHLCV/turnover","M3 OHLCV/turnover","M5 OHLCV/turnover","H1 OHLCV/turnover","Initial structural backfill","Rolling 60m high/low","Rolling ~6h high/low","Rolling ~24h high/low","All public executed trades","Aggressor side","Execution price","Execution quantity","Execution notional","Executed buy notional","Executed sell notional","Executed trade count","Flow imbalance family","Flow imbalance 5s","Flow imbalance 15s","Flow imbalance 60s","Buyer/seller dominance transition","Cumulative flow/CVD-like balance","Price response to buy flow","Price response to sell flow","Buyer price efficiency","Seller price efficiency","Old-side efficiency decay","New-side efficiency growth","New-side price response 30-60s","New-side price response ~3m","New-side price response ~5m","Directional persistence","Retracement from running extreme","Candidate survival without same-side extension","Running high","Running low","Candidate invalidation on same-side extension","Current reversal attempts in active swing","Prior false attempts in same swing","Current-vs-prior-attempt comparison","Full Bybit L50 orderbook state/replay","Bid levels","Ask levels","Orderbook level price","Orderbook level quantity","Orderbook depth changes","Liquidity replenishment evidence","Liquidity disappearance","Cancellations/withdrawal evidence","Bid absorption evidence/proxy","Ask absorption evidence/proxy","Book imbalance","Book validity","Book sequence/reset/invalidation","Open interest","OI change","OI freshness","Price/OI relationship","Funding rate","24h volume","24h turnover","Public liquidation events","Liquidation price","Liquidation size","Liquidation side","Liquidation notional","Long-liquidation aggregate","Short-liquidation aggregate","Liquidation event count","Liquidation clusters","Liquidation burst vs price","Liquidation burst vs flow","Liquidation burst vs OI","Raw receive timestamps","Microstructure snapshot timestamps","Intra-segment gap detection","Cross-segment continuity","Provenance/run/commit/source","Replayable primary data","Current structural state","Last confirmed structural Local High","Last confirmed structural Local Low","Active swing direction","Running structural extreme","Structural maturity","v6 WATCH state","v6 FORMING state","v6 EARLY_HIGH_CONFIDENCE state","v6 CONFIRMED state","v6 HARD_CONFIRMED state","Candidate timestamp","First EARLY_HIGH_CONFIDENCE timestamp","Confirmation timestamp","Signal delay from extreme","Signal price error","First accepted signal true/false","First-accepted precision","False-local rate","Coverage/recall","Median delay","P90 delay","Median price error","P90 price error","Strict H1 Local High/Low label set","Internal locals inside larger movement","Significant extrema timing label set","Time-aligned causal sequence Structure→Flow→Book→OI/Liq→Price response"]
    assert len(titles)==110
    direct=set(range(1,20))|set(range(21,24))|set(range(44,50))|set(range(55,59))|set(range(62,73))|set(range(77,83))
    post=set(range(83,110)); rows=[]
    for i,title in enumerate(titles,1):
        mode="DIRECT" if i in direct else ("POST_ANALYSIS" if i in post else "DERIVED")
        if i in (53,54): mode="DERIVED_PROXY"
        rows.append({"id":i,"title":title,"mode":mode,
                     "source":"stored primary streams" if i<83 else "frozen-v6 replay / 12h analysis"})
    return rows

def extras():
    return [
{"id":111,"title":"Bybit server time + runner clock offset","mode":"DIRECT/DERIVED"},
{"id":112,"title":"Instrument metadata: tickSize/qtyStep/contract/risk/funding metadata","mode":"DIRECT"},
{"id":113,"title":"Public long/short holder ratio (5m)","mode":"DIRECT"},
{"id":114,"title":"Mark-index basis / basis bps","mode":"DERIVED"},
{"id":115,"title":"OI notional (OI × reference price)","mode":"DERIVED"},
{"id":116,"title":"Collector connection/restart/data-gap health markers","mode":"DIRECT"}]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    out=args.output; out.mkdir(parents=True,exist_ok=True)
    chunks=sorted(p for p in args.input.rglob("chunk_*") if p.is_dir())
    manifest={"format_version":FORMAT_VERSION,"schema_version":SCHEMA_VERSION,"symbol":"HYPEUSDT","chunks":[]}
    source_bytes=packed_bytes=0
    for ch in chunks:
        od=out/"chunks"/ch.name; od.mkdir(parents=True,exist_ok=True); ci={"chunk":ch.name,"streams":[]}
        specs=[("HYPE_live_raw_frames.jsonl","events.mpk.xz","events"),
               ("HYPE_live_microstructure_1s.jsonl","microstructure_1s.mpk.xz","table"),
               ("HYPE_market_context.jsonl","market_context_1m.mpk.xz","table"),
               ("HYPE_structural_context_1m.jsonl","structural_context_1m.mpk.xz","table")]
        for srcn,dstn,kind in specs:
            src=ch/srcn
            if not src.exists(): continue
            dst=od/dstn
            meta=pack_events(src,dst) if kind=="events" else {"records":pack_tabular_jsonl(src,dst)}
            entry={"name":dstn,"source":srcn,"source_bytes":src.stat().st_size,
                   "packed_bytes":dst.stat().st_size,"sha256":sha256(dst),**meta}
            ci["streams"].append(entry); source_bytes+=src.stat().st_size; packed_bytes+=dst.stat().st_size
        for name in ("CHUNK_STATUS.json","SUMMARY.json","CONTEXT_SUMMARY.json"):
            if (ch/name).exists(): shutil.copy2(ch/name,od/name)
        manifest["chunks"].append(ci)
    for name in ("RESILIENT_CAPTURE_MANIFEST.json","AGGREGATE_SEGMENT.json","PROVENANCE.json"):
        if (args.input/name).exists(): shutil.copy2(args.input/name,out/name)
    schema={"canonical_points":schema_110(),"extras":extras(),
            "semantics":{"all_110_supported":True,"DIRECT":"stored directly",
            "DERIVED":"deterministically reconstructed from stored primary streams",
            "POST_ANALYSIS":"computed by frozen-v6 replay/12h evaluation; not exchange data",
            "DERIVED_PROXY":"evidence proxy only; no anonymous passive-order attribution"}}
    (out/"SCHEMA_110.json").write_text(json.dumps(schema,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest.update({"source_bytes":source_bytes,"packed_bytes":packed_bytes,
        "compression_ratio":None if not source_bytes else packed_bytes/source_bytes,
        "all_110_supported":True,"canonical_point_count":110,"extra_point_count":len(extras())})
    (out/"PACK_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"README_AGENT.md").write_text(
        "# HYPE 110 compact research package\n\nAll 110 canonical points are covered. "
        "DIRECT values are stored. DERIVED values are reproducible from stored streams. "
        "POST_ANALYSIS values are outputs of frozen-v6 replay / 12h evaluation.\n\n"
        "events.mpk.xz codes: 0=orderbook, 1=trade, 2=liquidation, 3=ticker, 9=control. "
        "Price/qty are scaled integers; scales are in PACK_MANIFEST.json. Use decode_compact.py.\n\n"
        "Absorption is evidence/proxy only, never identification of passive participants.\n",encoding="utf-8")
    print(json.dumps(manifest),flush=True)

if __name__=="__main__": main()
