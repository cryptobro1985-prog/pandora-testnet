"""Causal H1 structural context for a Local candidate snapshot.

Every value is computed from minute bars whose bar_end_ms <= snapshot_ts_ms.
The future K2 hours that define the strict teacher label are never inputs.
"""
from __future__ import annotations
import bisect,gzip,json,math

H=3_600_000

def load_minutes(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():rows.append(json.loads(line))
    rows.sort(key=lambda r:int(r["bar_end_ms"]))
    return rows

def build_index(minutes):
    ends=[int(r["bar_end_ms"]) for r in minutes]
    return ends

def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)

def aggregate(rows,start,end):
    q=[r for r in rows if start<=int(r["start_ms"]) and int(r["bar_end_ms"])<=end]
    if not q:return None
    return {"open":float(q[0]["open"]),"high":max(float(x["high"]) for x in q),
            "low":min(float(x["low"]) for x in q),"close":float(q[-1]["close"])}

def causal_h1_features(minutes,ends,snapshot_ts_ms,side,extreme_price):
    j=bisect.bisect_right(ends,int(snapshot_ts_ms))
    past=minutes[:j]
    if not past:return {}
    cur_hour=(int(snapshot_ts_ms)//H)*H
    completed=[]
    h=cur_hour-H
    for _ in range(8):
        b=aggregate(past,h,h+H)
        if b is not None:completed.append((h,b))
        h-=H
    completed=list(reversed(completed))
    if len(completed)<6:return {}
    prev6=[b for _,b in completed[-6:]]
    partial=aggregate(past,cur_hour,int(snapshot_ts_ms))
    if partial is None:return {}
    prev_hi=max(b["high"] for b in prev6);prev_lo=min(b["low"] for b in prev6)
    rng=max(partial["high"]-partial["low"],1e-9)
    span=max(prev_hi-prev_lo,1e-9)
    sign=1.0 if side=="LOW" else -1.0
    close=partial["close"];op=partial["open"]
    out={
      "teacherctx_h1_break_high_bps":(float(extreme_price)/max(prev_hi,1e-9)-1.0)*10000.0,
      "teacherctx_h1_break_low_bps":(prev_lo/max(float(extreme_price),1e-9)-1.0)*10000.0,
      "teacherctx_h1_side_break_bps":((prev_lo/max(float(extreme_price),1e-9)-1.0)*10000.0 if side=="LOW" else
                                      (float(extreme_price)/max(prev_hi,1e-9)-1.0)*10000.0),
      "teacherctx_h1_partial_body_rev_bps":sign*(close/max(op,1e-9)-1.0)*10000.0,
      "teacherctx_h1_partial_range_bps":(partial["high"]/max(partial["low"],1e-9)-1.0)*10000.0,
      "teacherctx_h1_partial_close_position":(close-partial["low"])/rng,
      "teacherctx_h1_partial_extreme_position":((float(extreme_price)-prev_lo)/span if side=="LOW" else
                                                (prev_hi-float(extreme_price))/span),
      "teacherctx_h1_retrace_from_extreme_bps":sign*(close/max(float(extreme_price),1e-9)-1.0)*10000.0,
      "teacherctx_prev6_trend_rev_bps":sign*(prev6[-1]["close"]/max(prev6[0]["open"],1e-9)-1.0)*10000.0,
      "teacherctx_prev3_trend_rev_bps":sign*(prev6[-1]["close"]/max(prev6[-3]["open"],1e-9)-1.0)*10000.0,
      "teacherctx_hour_progress":(int(snapshot_ts_ms)-cur_hour)/H,
    }
    return {k:float(v) for k,v in out.items() if finite(v)}
