from __future__ import annotations

import argparse, hashlib, json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.hype_full_micro_202607 import build_full_micro as base

KINDS=("trades","orderbook","liquidations","open_interest","mark_price","ticker")

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--hours",type=int,default=48)
    ap.add_argument("--workers",type=int,default=32)
    ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--manifest",type=Path,required=True)
    args=ap.parse_args()
    args.cache.mkdir(parents=True,exist_ok=True)
    args.manifest.parent.mkdir(parents=True,exist_ok=True)

    end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    start=end-timedelta(hours=args.hours)

    src=base.Source(args.cache,(os.getenv("CRYPTOHFTDATA_API_KEY") or "").strip() or None)
    base.prefetch_hours(src,start,end,KINDS,workers=args.workers)

    files=[]
    for p in sorted(args.cache.glob("*.parquet")):
        files.append({
            "name":p.name,
            "bytes":p.stat().st_size,
            "sha256":sha256_file(p),
        })

    expected=args.hours*len(KINDS)
    manifest={
        "version":"HYPE-RECENT48-RAW-DOWNLOAD-v1",
        "symbol":"HYPEUSDT",
        "exchange":"bybit",
        "window_utc":[start.isoformat(),end.isoformat()],
        "hours":args.hours,
        "kinds":list(KINDS),
        "expected_partitions":expected,
        "downloaded_files":src.downloads,
        "downloaded_bytes":src.bytes,
        "source_file_counts":dict(src.counts),
        "missing_files":sorted(set(src.missing)),
        "missing_files_count":len(set(src.missing)),
        "cache_file_count":len(files),
        "cache_bytes":sum(x["bytes"] for x in files),
        "files":files,
        "analysis_performed":False,
        "teacher_used":False,
        "note":"raw source download only; no replay, labels, training or Local decisions",
    }
    args.manifest.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    print("RAW48="+json.dumps({k:manifest[k] for k in (
        "window_utc","expected_partitions","downloaded_files","downloaded_bytes",
        "source_file_counts","missing_files_count","cache_file_count","cache_bytes"
    )},separators=(",",":"),ensure_ascii=False))

if __name__=="__main__":
    main()
