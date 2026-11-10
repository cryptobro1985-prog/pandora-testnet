#!/usr/bin/env python3
"""Ex-post directional path benchmark; NEVER use outputs as predictive features.

CSV required: timestamp,price. Optional: executable_bid,executable_ask.
The benchmark is a hindsight upper bound with a fixed minimum excursion,
fee/spread/slippage friction, and sequential non-overlapping trades.
It is NOT an achievable trading strategy.
"""
import argparse
import csv
import json
from datetime import datetime, timezone

def load_rows(path):
    out = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            ts = row["timestamp"]
            try:
                sec = float(ts)
                if sec > 1e11: sec /= 1000.0
            except ValueError:
                sec = datetime.fromisoformat(ts.replace("Z","+00:00")).timestamp()
            px = float(row["price"])
            if px <= 0: raise ValueError("Nonpositive price")
            bid = float(row.get("executable_bid") or px)
            ask = float(row.get("executable_ask") or px)
            if not (0 < bid <= ask): raise ValueError("Invalid bid/ask")
            out.append((sec, px, bid, ask))
    out.sort(key=lambda r:r[0])
    if any(a[0]>=b[0] for a,b in zip(out,out[1:])):
        raise ValueError("Duplicate/non-increasing timestamps")
    return out

def benchmark(rows, threshold, fee_bps=6, slip_bps=2, max_gap_seconds=300):
    """Optimal sequential nonoverlapping round trips, ex-post, with threshold.

    DP maximizes summed simple underlying trade returns, not compounded equity.
    A new trade can start only after prior exit. Per-side fees/slippage apply
    on entry and exit. No leverage or liquidation assumptions.
    """
    if not rows: return {"trades":[],"total_net_pct":0,"long_net_pct":0,"short_net_pct":0}
    segments=[]; segment=[rows[0]]
    for row in rows[1:]:
        if row[0]-segment[-1][0]>max_gap_seconds:
            segments.append(segment);segment=[]
        segment.append(row)
    segments.append(segment)
    trades=[]
    for seg in segments:
        n=len(seg)
        if n<2:continue
        dp=[0.0]*(n+1)
        choice=[None]*(n+1)
        # O(n^2) reference implementation: suitable for minute-bars per day.
        # Candidate PnL uses executable prices, explicit two-sided friction.
        for j in range(1,n):
            dp[j+1]=dp[j];choice[j+1]=None
            exit_time,_,exit_bid,exit_ask=seg[j]
            for i in range(j):
                entry_time,_,entry_bid,entry_ask=seg[i]
                cost=2*(fee_bps+slip_bps)/10000
                long_ret=exit_bid/entry_ask-1-cost
                short_ret=1-exit_ask/entry_bid-cost
                for side,ret in (("LONG",long_ret),("SHORT",short_ret)):
                    if ret < threshold: continue
                    score=dp[i]+ret
                    if score>dp[j+1]+1e-12:
                        dp[j+1]=score
                        choice[j+1]=(i,j,side,ret)
        j=n;selected=[]
        while j>0:
            c=choice[j]
            if c is None:j-=1;continue
            i,k,side,ret=c
            selected.append({"entry_time":datetime.fromtimestamp(seg[i][0],timezone.utc).isoformat(),
                             "exit_time":datetime.fromtimestamp(seg[k][0],timezone.utc).isoformat(),
                             "side":side,"net_underlying_pct":100*ret,
                             "entry_mid":seg[i][1],"exit_mid":seg[k][1]})
            j=i
        trades.extend(reversed(selected))
    return {"trades":trades,
            "trade_count":len(trades),
            "total_net_pct":sum(x["net_underlying_pct"] for x in trades),
            "long_net_pct":sum(x["net_underlying_pct"] for x in trades if x["side"]=="LONG"),
            "short_net_pct":sum(x["net_underlying_pct"] for x in trades if x["side"]=="SHORT"),
            "interpretation":"Hindsight upper bound; cannot be traded without future knowledge."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--thresholds",default="0.0025,0.0035,0.005,0.0075,0.01")
    p.add_argument("--fee-bps",type=float,default=6)
    p.add_argument("--slip-bps",type=float,default=2)
    p.add_argument("--max-gap-seconds",type=float,default=300)
    args=p.parse_args()
    rows=load_rows(args.csv)
    days={}
    for row in rows:
        day=datetime.fromtimestamp(row[0],timezone.utc).date().isoformat()
        days.setdefault(day,[]).append(row)
    result={"source":args.csv,"fee_bps_per_side":args.fee_bps,
            "slip_bps_per_side":args.slip_bps,"days":{}}
    for day,day_rows in days.items():
        result["days"][day]={str(t):benchmark(day_rows,float(t),args.fee_bps,args.slip_bps,args.max_gap_seconds)
                             for t in args.thresholds.split(",")}
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
