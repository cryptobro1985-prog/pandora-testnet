#!/usr/bin/env python3
"""Fault-tolerant research-only wrapper for HYPE forward capture.

Runs microstructure + structural-context collectors in short chunks so a transient
WebSocket/REST/process failure cannot wipe an entire multi-hour segment. Each
chunk is written to its own directory and a manifest records success/failure.
No trading endpoints or order placement.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path

def run_pair(root: Path, idx: int, minutes: int) -> dict:
    out = root / "chunks" / f"chunk_{idx:04d}"
    out.mkdir(parents=True, exist_ok=True)
    live_log=(out/"live.log").open("w", encoding="utf-8")
    ctx_log=(out/"context.log").open("w", encoding="utf-8")
    start=time.time()
    live=subprocess.Popen([sys.executable,"research/hype_local_v5/research.py","--mode","live","--minutes",str(minutes),"--output",str(out)],stdout=live_log,stderr=subprocess.STDOUT)
    ctx=subprocess.Popen([sys.executable,"research/hype_local_v5/context_capture.py","--minutes",str(minutes),"--output",str(out)],stdout=ctx_log,stderr=subprocess.STDOUT)
    live_rc=live.wait()
    ctx_rc=ctx.wait()
    live_log.close(); ctx_log.close()
    return {"chunk":idx,"requested_minutes":minutes,"started_ts_ms":int(start*1000),"ended_ts_ms":int(time.time()*1000),"live_rc":live_rc,"context_rc":ctx_rc,"path":str(out)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--minutes",type=int,required=True)
    ap.add_argument("--chunk-minutes",type=int,default=20)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    deadline=time.time()+args.minutes*60
    manifest={"research_only":True,"symbol":"HYPEUSDT","target_minutes":args.minutes,"chunk_minutes":args.chunk_minutes,"git_sha":os.getenv("GITHUB_SHA"),"run_id":os.getenv("GITHUB_RUN_ID"),"chunks":[]}
    idx=0
    consecutive_total_failures=0
    while time.time() < deadline-5:
        idx+=1
        remaining=max(1,int((deadline-time.time())/60))
        mins=max(1,min(args.chunk_minutes,remaining))
        rec=run_pair(args.output,idx,mins)
        manifest["chunks"].append(rec)
        (args.output/"RESILIENT_CAPTURE_MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
        if rec["live_rc"]!=0 and rec["context_rc"]!=0:
            consecutive_total_failures+=1
            # brief backoff, then automatically continue
            time.sleep(min(60,10*consecutive_total_failures))
        else:
            consecutive_total_failures=0
    manifest["completed_ts_ms"]=int(time.time()*1000)
    manifest["chunks_ok_any"]=sum(1 for x in manifest["chunks"] if x["live_rc"]==0 or x["context_rc"]==0)
    manifest["chunks_both_ok"]=sum(1 for x in manifest["chunks"] if x["live_rc"]==0 and x["context_rc"]==0)
    (args.output/"RESILIENT_CAPTURE_MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    # Fail only if nothing at all was captured; partial chunks are preserved.
    if manifest["chunks_ok_any"]==0:
        raise SystemExit(2)
    print(json.dumps(manifest),flush=True)

if __name__=="__main__":
    main()
