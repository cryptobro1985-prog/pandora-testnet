#!/usr/bin/env python3
"""Linear-time hindsight tradeable-path benchmark with explicit execution delay.

Evaluation only: future prices determine the optimal sequence. NEVER feed the
output, chosen trades or path labels into live predictive features.
"""
from __future__ import annotations
import argparse, csv, json
from datetime import datetime, timezone

def parse_csv(path):
    rows=[]
    with open(path,newline="") as f:
        for r in csv.DictReader(f):
            s=r["timestamp"]
            try:
                t=float(s)
                if t>1e11:t/=1000
            except ValueError:
                t=datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
            mid=float(r["price"])
            bid=float(r.get("executable_bid") or mid)
            ask=float(r.get("executable_ask") or mid)
            if not (0<bid<=ask):raise ValueError("bad bid/ask")
            rows.append((t,mid,bid,ask))
    rows.sort()
    if any(b[0]<=a[0] for a,b in zip(rows,rows[1:])):
        raise ValueError("duplicate timestamps")
    return rows

def segments(rows,gap):
    current=[]
    for r in rows:
        if current and r[0]-current[-1][0]>gap:
            yield current
            current=[]
        current.append(r)
    if current:yield current

def oracle(rows, min_net_return=.0025, fee_bps=6, slip_bps=2,
           max_gap_seconds=300, min_hold_seconds=60, cooldown_seconds=60):
    """Ex-post max sum of simple returns, non-overlapping trades.

    No same-timestamp flip; next entry must follow exit by cooldown_seconds.
    A minimum holding time prevents zero-duration excursions.
    O(n^2) by design for auditability; intended for day-scoped minute data.
    All friction is charged on both sides. No intrabar high/low fills.
    """
    if min_net_return<0 or min_hold_seconds<0 or cooldown_seconds<0:
        raise ValueError("negative constraint")
    if fee_bps<0 or slip_bps<0:raise ValueError("negative cost")
    all_trades=[]
    friction=2*(fee_bps+slip_bps)/10000
    for seg in segments(rows,max_gap_seconds):
        n=len(seg)
        if n<2:continue
        best=[0.0]*(n+1)
        prev=[None]*(n+1)
        for j in range(n):
            best[j+1]=best[j]
            prev[j+1]=None
            t_exit,px_exit,bid_exit,ask_exit=seg[j]
            for i in range(j):
                t_entry,px_entry,bid_entry,ask_entry=seg[i]
                if t_exit-t_entry<min_hold_seconds:continue
                # Last completed exit must precede this entry by cooldown.
                prior_candidates=[k for k in range(i) if t_entry-seg[k][0]>=cooldown_seconds]
                prior_idx=(prior_candidates[-1]+1) if prior_candidates else 0
                base=best[prior_idx]
                for side,ret in (("LONG",bid_exit/ask_entry-1-friction),
                                 ("SHORT",1-ask_exit/bid_entry-friction)):
                    if ret<min_net_return:continue
                    score=base+ret
                    if score>best[j+1]+1e-12:
                        best[j+1]=score
                        prev[j+1]=(prior_idx,i,j,side,ret)
        j=n
        selected=[]
        while j:
            p=prev[j]
            if p is None:j-=1;continue
            prior,i,k,side,ret=p
            selected.append({
                "entry_time":datetime.fromtimestamp(seg[i][0],timezone.utc).isoformat(),
                "exit_time":datetime.fromtimestamp(seg[k][0],timezone.utc).isoformat(),
                "side":side,"net_underlying_pct":ret*100,
                "entry_mid":seg[i][1],"exit_mid":seg[k][1]})
            j=prior
        all_trades.extend(reversed(selected))
    return {
        "trade_count":len(all_trades),"trades":all_trades,
        "total_net_pct":sum(t["net_underlying_pct"] for t in all_trades),
        "long_net_pct":sum(t["net_underlying_pct"] for t in all_trades if t["side"]=="LONG"),
        "short_net_pct":sum(t["net_underlying_pct"] for t in all_trades if t["side"]=="SHORT"),
        "interpretation":"Ex-post evaluation upper bound, not an executable strategy"
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--thresholds",default="0.0025,0.0035,0.005,0.0075,0.01")
    p.add_argument("--fee-bps",type=float,default=6)
    p.add_argument("--slip-bps",type=float,default=2)
    p.add_argument("--max-gap-seconds",type=float,default=300)
    p.add_argument("--min-hold-seconds",type=float,default=60)
    p.add_argument("--cooldown-seconds",type=float,default=60)
    a=p.parse_args()
    days={}
    for r in parse_csv(a.csv):
        day=datetime.fromtimestamp(r[0],timezone.utc).date().isoformat()
        days.setdefault(day,[]).append(r)
    report={"source":a.csv,"days":{},
            "assumptions":{"fee_bps_per_side":a.fee_bps,"slip_bps_per_side":a.slip_bps,
            "max_gap_seconds":a.max_gap_seconds,"min_hold_seconds":a.min_hold_seconds,
            "cooldown_seconds":a.cooldown_seconds}}
    for day,rows in days.items():
        report["days"][day]={str(t):oracle(rows,float(t),a.fee_bps,a.slip_bps,
            a.max_gap_seconds,a.min_hold_seconds,a.cooldown_seconds)
            for t in a.thresholds.split(",")}
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
