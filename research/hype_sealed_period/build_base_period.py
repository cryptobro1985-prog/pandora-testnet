from __future__ import annotations
import argparse
from datetime import datetime,timezone,timedelta
from pathlib import Path
import research.local_116_30d.run_symbol as base

def dt(s):
    return datetime.strptime(s,"%Y-%m-%d").replace(tzinfo=timezone.utc)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",required=True)
    ap.add_argument("--end",required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--cache",type=Path,required=True)
    args=ap.parse_args()
    start=dt(args.start); end=dt(args.end)
    span=end-start
    base.START=start
    base.DISCOVERY=start+timedelta(days=4)
    base.TRAIN_END=start+timedelta(days=max(5,int(span.days*0.60)))
    base.OOS=start+timedelta(days=max(6,int(span.days*0.80)))
    base.END=end
    base.run("HYPE",args.output,args.cache)

if __name__=="__main__":
    main()
