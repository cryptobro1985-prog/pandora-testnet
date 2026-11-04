#!/usr/bin/env python3
"""Fast self-test for compact HYPE research format."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def jline(path,obj):
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(obj,separators=(",",":"))+"\n")

def main():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/"capture"; ch=root/"chunks"/"chunk_0001"; ch.mkdir(parents=True)
        frames=[
          {"received_ts_ms":1000,"receipt_sequence":1,"endpoint":"wss://example",
           "raw_text":json.dumps({"op":"subscribe","success":True})},
          {"received_ts_ms":1010,"receipt_sequence":2,"endpoint":"wss://example",
           "raw_text":json.dumps({"topic":"orderbook.50.HYPEUSDT","type":"snapshot","ts":1005,
             "data":{"u":10,"seq":100,"b":[["86.227","11.00"],["86.226","7.13"]],"a":[["86.228","16.34"]]}})},
          {"received_ts_ms":1020,"receipt_sequence":3,"endpoint":"wss://example",
           "raw_text":json.dumps({"topic":"orderbook.50.HYPEUSDT","type":"delta","ts":1015,
             "data":{"u":11,"seq":101,"b":[["86.227","10.00"]],"a":[["86.229","1.00"]]}})},
          {"received_ts_ms":1030,"receipt_sequence":4,"endpoint":"wss://example",
           "raw_text":json.dumps({"topic":"publicTrade.HYPEUSDT","ts":1025,
             "data":[{"T":1025,"s":"HYPEUSDT","S":"Buy","v":"0.41","p":"86.228","L":"PlusTick","i":"x","BT":False,"RPI":False,"seq":102}]})},
          {"received_ts_ms":1040,"receipt_sequence":5,"endpoint":"wss://example",
           "raw_text":json.dumps({"topic":"allLiquidation.HYPEUSDT","ts":1035,
             "data":[{"T":1035,"s":"HYPEUSDT","S":"Sell","v":"1.25","p":"86.200"}]})},
          {"received_ts_ms":1050,"receipt_sequence":6,"endpoint":"wss://example",
           "raw_text":json.dumps({"topic":"tickers.HYPEUSDT","ts":1045,
             "data":{"lastPrice":"86.23","markPrice":"86.22","indexPrice":"86.21","openInterest":"12345","fundingRate":"0.0001","volume24h":"99","turnover24h":"888"}})}
        ]
        for x in frames:jline(ch/"HYPE_live_raw_frames.jsonl",x)
        jline(ch/"HYPE_live_microstructure_1s.jsonl",{"ts_ms":1000,"mid":86.2275,"book_valid":True,"flow_imbalance_60s":0.2})
        jline(ch/"HYPE_market_context.jsonl",{"received_ts_ms":1000,"symbol":"HYPEUSDT","candles":{"1":[]},"ticker":{"lastPrice":"86.23"}})
        jline(ch/"HYPE_structural_context_1m.jsonl",{"ts_ms":1000,"symbol":"HYPEUSDT","last_price":86.23})
        out=Path(td)/"compact"
        subprocess.check_call([sys.executable,str(ROOT/"compact_pack.py"),"--input",str(root),"--output",str(out)])
        subprocess.check_call([sys.executable,str(ROOT/"decode_compact.py"),str(out),"--verify"])
        schema=json.loads((out/"SCHEMA_110.json").read_text())
        assert len(schema["canonical_points"])==110
        from decode_compact import manifest,chunk_meta,stream_meta,decode_events
        m=manifest(out); c=chunk_meta(m,"chunk_0001"); meta=stream_meta(c,"events.mpk.xz")
        rows=list(decode_events(out/"chunks"/"chunk_0001"/"events.mpk.xz",meta))
        assert [r["kind"] for r in rows]==["control","orderbook","orderbook","trade","liquidation","ticker"]
        assert rows[1]["bids"][0]==[86.227,11.0]
        assert rows[2]["bids"][0]==[86.227,10.0]
        assert rows[3]["price"]==86.228 and rows[3]["qty"]==0.41
        assert rows[4]["price"]==86.2 and rows[4]["qty"]==1.25
        print("COMPACT_SMOKE_OK")

if __name__=="__main__":main()
