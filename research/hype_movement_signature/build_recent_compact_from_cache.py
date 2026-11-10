#!/usr/bin/env python3
from __future__ import annotations
import argparse, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from research.hype_full_micro_202607 import build_full_micro as base


def parse_dt(s:str):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",required=True)
    ap.add_argument("--end",required=True)
    ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--workers",type=int,default=32)
    a=ap.parse_args()
    start,end=parse_dt(a.start),parse_dt(a.end)
    if end<=start:raise ValueError("end <= start")
    a.output.parent.mkdir(parents=True,exist_ok=True)

    # load_trades uses module START/END. Labels/orderbook/Local logic are not called.
    base.START=start;base.END=end
    src=base.Source(a.cache,(os.getenv("CRYPTOHFTDATA_API_KEY") or "").strip() or None)
    base.prefetch_hours(src,start-timedelta(hours=24),end,("trades",),workers=a.workers)
    _,mins,_=base.load_trades(src)
    sm=base.ms(start);em=base.ms(end)
    rows=[r for r in mins if sm<=int(r["start_ms"])<em]
    if not rows:raise RuntimeError("no minute rows")
    base.write_jsonl_gz(a.output,rows)
    print({
      "rows":len(rows),"first_start_ms":rows[0]["start_ms"],"last_start_ms":rows[-1]["start_ms"],
      "downloads":src.downloads,"downloaded_bytes":src.bytes,"missing":len(src.missing)
    })


if __name__=="__main__":main()
