"""Causal H1 structural context for a Local candidate snapshot.

All values use only minute bars with bar_end_ms <= snapshot_ts_ms.
Future K2 hours define the teacher label only and are never model inputs.
The index makes feature extraction O(1) per snapshot apart from <=60 current
hour minute bars.
"""
from __future__ import annotations
import bisect,gzip,json,math
from collections import defaultdict

H=3_600_000

def load_minutes(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():rows.append(json.loads(line))
    rows.sort(key=lambda r:int(r["bar_end_ms"]))
    return rows

def _ohlc(q):
    if not q:return None
    return {"open":float(q[0]["open"]),"high":max(float(x["high"]) for x in q),
            "low":min(float(x["low"]) for x in q),"close":float(q[-1]["close"])}

def build_index(minutes):
    hours=defaultdict(list)
    for r in minutes:
        h=(int(r["start_ms"])//H)*H
        hours[h].append(r)
    full={};hour_ends={}
    for h,q in hours.items():
        q.sort(key=lambda r:int(r["bar_end_ms"]))
        hour_ends[h]=[int(r["bar_end_ms"]) for r in q]
        contiguous=(q and int(q[0]["start_ms"])==h and int(q[-1]["bar_end_ms"])==h+H
                    and all(int(b["start_ms"])==int(a["bar_end_ms"]) for a,b in zip(q,q[1:])))
        if contiguous:full[h]=_ohlc(q)
    return {"hours":dict(hours),"hour_ends":hour_ends,"full":full}

def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)

def causal_h1_features(minutes,index,snapshot_ts_ms,side,extreme_price):
    t=int(snapshot_ts_ms);cur_hour=(t//H)*H
    prev6=[]
    for k in range(6,0,-1):
        b=index["full"].get(cur_hour-k*H)
        if b is None:return {}
        prev6.append(b)
    q=index["hours"].get(cur_hour) or []
    ends=index["hour_ends"].get(cur_hour) or []
    j=bisect.bisect_right(ends,t)
    partial=_ohlc(q[:j])
    if partial is None:return {}
    prev_hi=max(b["high"] for b in prev6);prev_lo=min(b["low"] for b in prev6)
    rng=max(partial["high"]-partial["low"],1e-9);span=max(prev_hi-prev_lo,1e-9)
    sign=1.0 if side=="LOW" else -1.0
    close=partial["close"];op=partial["open"];px=float(extreme_price)
    out={
      "teacherctx_h1_break_high_bps":(px/max(prev_hi,1e-9)-1.0)*10000.0,
      "teacherctx_h1_break_low_bps":(prev_lo/max(px,1e-9)-1.0)*10000.0,
      "teacherctx_h1_side_break_bps":((prev_lo/max(px,1e-9)-1.0)*10000.0 if side=="LOW" else
                                      (px/max(prev_hi,1e-9)-1.0)*10000.0),
      "teacherctx_h1_partial_body_rev_bps":sign*(close/max(op,1e-9)-1.0)*10000.0,
      "teacherctx_h1_partial_range_bps":(partial["high"]/max(partial["low"],1e-9)-1.0)*10000.0,
      "teacherctx_h1_partial_close_position":(close-partial["low"])/rng,
      "teacherctx_h1_partial_extreme_position":((px-prev_lo)/span if side=="LOW" else (prev_hi-px)/span),
      "teacherctx_h1_retrace_from_extreme_bps":sign*(close/max(px,1e-9)-1.0)*10000.0,
      "teacherctx_prev6_trend_rev_bps":sign*(prev6[-1]["close"]/max(prev6[0]["open"],1e-9)-1.0)*10000.0,
      "teacherctx_prev3_trend_rev_bps":sign*(prev6[-1]["close"]/max(prev6[-3]["open"],1e-9)-1.0)*10000.0,
      "teacherctx_hour_progress":(t-cur_hour)/H,
    }
    return {k:float(v) for k,v in out.items() if finite(v)}
