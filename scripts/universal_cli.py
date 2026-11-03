from __future__ import annotations
import argparse
from pathlib import Path
from universal_data import aggregate_symbol,dt
from universal_optimize import main as optimize_main

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("aggregate");a.add_argument("--symbol",required=True);a.add_argument("--start",required=True);a.add_argument("--end",required=True);a.add_argument("--output",type=Path,required=True);a.add_argument("--cache",type=Path,required=True)
    o=sub.add_parser("optimize");o.add_argument("--input",type=Path,required=True);o.add_argument("--output",type=Path,required=True);o.add_argument("--split-date",default="2026-10-27");o.add_argument("--candidates",type=int,default=220)
    args=ap.parse_args()
    if args.cmd=="aggregate":
        print(aggregate_symbol(args.symbol,dt(args.start),dt(args.end),args.output,args.cache))
    else:
        import sys
        sys.argv=["universal_optimize.py","--input",str(args.input),"--output",str(args.output),"--split-date",args.split_date,"--candidates",str(args.candidates)]
        optimize_main()
if __name__=="__main__":main()
