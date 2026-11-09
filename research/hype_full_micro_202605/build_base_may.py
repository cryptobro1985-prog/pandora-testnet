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

    # New sealed regime. Build tape only; do not replay any detector here.
    base.START=datetime(2026,5,1,0,tzinfo=timezone.utc)
    base.DISCOVERY=datetime(2026,5,5,0,tzinfo=timezone.utc)
    base.TRAIN_END=datetime(2026,5,19,0,tzinfo=timezone.utc)
    base.OOS=datetime(2026,5,25,0,tzinfo=timezone.utc)
    base.END=datetime(2026,6,1,0,tzinfo=timezone.utc)
    base.run("HYPE",args.output,args.cache)

if __name__=="__main__":
    main()
