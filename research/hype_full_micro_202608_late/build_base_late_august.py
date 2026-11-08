from __future__ import annotations
import argparse
from datetime import datetime,timezone
from pathlib import Path
import research.local_116_30d.run_symbol as base

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--cache",type=Path,required=True)
    args=ap.parse_args()

    # Fourth compact window. Built before any HYPE stack is scored on it.
    # Stack thresholds/architecture MUST NOT be selected from this period.
    base.START=datetime(2026,8,8,0,tzinfo=timezone.utc)
    base.DISCOVERY=datetime(2026,8,10,0,tzinfo=timezone.utc)
    base.TRAIN_END=datetime(2026,8,21,0,tzinfo=timezone.utc)
    base.OOS=datetime(2026,8,27,0,tzinfo=timezone.utc)
    base.END=datetime(2026,9,1,0,tzinfo=timezone.utc)
    base.run("HYPE",args.output,args.cache)

if __name__=="__main__":
    main()
