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

    # Same H1 teacher/candidate logic as the audited 30D pipeline, but on Jul-Aug.
    base.START=datetime(2026,7,12,17,tzinfo=timezone.utc)
    base.DISCOVERY=datetime(2026,7,16,tzinfo=timezone.utc)
    base.TRAIN_END=datetime(2026,7,29,tzinfo=timezone.utc)
    base.OOS=datetime(2026,8,2,tzinfo=timezone.utc)
    base.END=datetime(2026,8,7,tzinfo=timezone.utc)
    base.run("HYPE",args.output,args.cache)

if __name__=="__main__":
    main()
