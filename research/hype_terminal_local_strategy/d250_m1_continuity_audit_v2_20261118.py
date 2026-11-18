#!/usr/bin/env python3
"""D250 M1 coverage audit v2: order-independent exact coverage; research only."""
import argparse, csv, hashlib, json
from collections import Counter
from datetime import datetime, timezone

def minute(value):
    s = str(value).strip()
    if s.isdigit():
        n = int(s)
        if n > 10**14: raise ValueError("ambiguous numeric timestamp")
        d = datetime.fromtimestamp(n/1000 if n >= 10**12 else n, timezone.utc)
    else:
        d = datetime.fromisoformat(s.replace("Z","+00:00"))
        if d.tzinfo is None: raise ValueError("naive timestamp")
        d = d.astimezone(timezone.utc)
    if d.second or d.microsecond: raise ValueError("unaligned M1 timestamp")
    return int(d.timestamp()//60)

def audit_rows(rows, start, end):
    start, end = minute(start), minute(end)
    if end < start: raise ValueError("invalid window")
    seen=Counter()
    prev=None
    disorder=0
    outside=0
    for raw in rows:
        t=minute(raw)
        if prev is not None and t<prev: disorder+=1
        prev=t
        seen[t]+=1
        if t<start or t>end: outside+=1
    unique_in_window=sorted(t for t in seen if start<=t<=end)
    missing=[]
    cursor=start
    for t in unique_in_window:
        if t>cursor: missing.append([cursor,t-1])
        cursor=t+1
    if cursor<=end: missing.append([cursor,end])
    duplicates=sum(v-1 for v in seen.values() if v>1)
    missing_count=sum(b-a+1 for a,b in missing)
    return dict(rows=sum(seen.values()), unique_minutes=len(seen),
                expected_minutes=end-start+1, missing_minutes=missing_count,
                missing_intervals_utc_minutes=missing[:100],
                missing_interval_count=len(missing), duplicate_rows=duplicates,
                out_of_order_transitions=disorder, outside_window_rows=outside,
                verified_continuous=(missing_count==0 and duplicates==0 and disorder==0 and outside==0),
                scope="timestamps only; no proof of Bybit provenance, prices, execution or PnL")

def audit_csv(path, column, start, end):
    digest=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): digest.update(chunk)
    with open(path,newline="") as f:
        reader=csv.DictReader(f)
        if column not in (reader.fieldnames or []): raise ValueError("timestamp column absent")
        result=audit_rows((row[column] for row in reader),start,end)
    result.update(file=path,sha256=digest.hexdigest())
    return result

def selftest():
    a=minute("2026-11-01T00:00:00Z")*60
    ts=lambda x:str((a+60*x))
    assert audit_rows([ts(0),ts(1),ts(2)],ts(0),ts(2))["verified_continuous"]
    x=audit_rows([ts(0),ts(2),ts(1),ts(2)],ts(0),ts(2))
    assert x["missing_minutes"]==0 and x["duplicate_rows"]==1 and x["out_of_order_transitions"]==1
    x=audit_rows([ts(0),ts(2)],ts(0),ts(2))
    assert x["missing_minutes"]==1 and x["missing_interval_count"]==1
    x=audit_rows([ts(0),ts(1),ts(1),ts(2)],ts(0),ts(2))
    assert x["duplicate_rows"]==1 and not x["verified_continuous"]
    x=audit_rows([ts(-1),ts(0),ts(1),ts(2)],ts(0),ts(2))
    assert x["outside_window_rows"]==1 and not x["verified_continuous"]
    print("5 synthetic regression cases passed")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("csv",nargs="?")
    p.add_argument("--timestamp-column",default="timestamp")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest: selftest()
    else:
        if not (a.csv and a.start and a.end): p.error("csv, --start and --end required")
        print(json.dumps(audit_csv(a.csv,a.timestamp_column,a.start,a.end),indent=2))
