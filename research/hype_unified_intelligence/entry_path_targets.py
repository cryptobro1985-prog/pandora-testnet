#!/usr/bin/env python3
"""Evaluation-only HYPE LONG/SHORT path labels from completed minute bars.

FUTURE DATA: do not import any output of this module into predictive X.
This is a label builder, NOT an execution simulator. Candle high/low are NOT
assumed executable prices. Same-bar favorable/adverse hit is ambiguous.
"""
from __future__ import annotations
import math

HORIZONS=(3,5,10,15,30,60,120)
TARGET_BPS=(25,35,50,75,100,150,200)
DEFAULT_ADVERSE_BPS=35

def _finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def validate_future(entry_end_ms,entry_close,future_bars,max_horizon):
    if not _finite(entry_close) or entry_close<=0:
        raise ValueError("invalid entry close")
    if not isinstance(entry_end_ms,int) or entry_end_ms<=0:
        raise ValueError("invalid entry timestamp")
    if len(future_bars)<max_horizon:
        raise ValueError("insufficient future horizon")
    for i,r in enumerate(future_bars[:max_horizon]):
        ts=r.get("bar_end_ms")
        if not isinstance(ts,int) or ts!=entry_end_ms+(i+1)*60000:
            raise ValueError("future minute gap or duplicate")
        lo=r.get("low"); hi=r.get("high"); close=r.get("close")
        if not all(_finite(v) for v in (lo,hi,close)) or lo<=0 or lo>close or close>hi:
            raise ValueError("invalid future candle")
        if r.get("gap",False):
            raise ValueError("future data quality gap")
    return True

def _first_before(good,bad,up_bps,adverse_bps):
    """Returns 1, 0 or None when neither barrier is hit.

    Both barriers touched in one minute => 0 (conservatively NOT a success)
    because OHLC does not establish intraminute execution ordering.
    """
    for g,b in zip(good,bad):
        g_hit=g>=up_bps
        b_hit=b>=adverse_bps
        if b_hit:return 0
        if g_hit:return 1
    return None

def label_path(entry_end_ms,entry_close,future_bars,horizons=HORIZONS,
               target_bps=TARGET_BPS,adverse_bps=DEFAULT_ADVERSE_BPS):
    horizons=tuple(sorted(set(int(h) for h in horizons)))
    if not horizons or horizons[0]<1:
        raise ValueError("invalid horizons")
    validate_future(entry_end_ms,entry_close,future_bars,max(horizons))
    report={"entry_end_ms":int(entry_end_ms),
            "entry_price":float(entry_close),
            "role":"TARGET_EVAL_ONLY","future_used_as_predictor":False,
            "threshold_bps":list(target_bps),"adverse_bps":int(adverse_bps),
            "horizons":{}}
    for h in horizons:
        q=future_bars[:h]
        highs=[float(r["high"]) for r in q]
        lows=[float(r["low"]) for r in q]
        closes=[float(r["close"]) for r in q]
        up=[(v/entry_close-1.0)*10000 for v in highs]
        down=[(1.0-v/entry_close)*10000 for v in lows]
        close_returns=[(v/entry_close-1.0)*10000 for v in closes]
        total_path=sum(abs(b-a) for a,b in zip([0.0]+close_returns[:-1],close_returns))
        side={}
        for s in ("LONG","SHORT"):
            favorable=up if s=="LONG" else down
            adverse=down if s=="LONG" else up
            raw_mfe=max(0.0,max(favorable))
            raw_mae=max(0.0,max(adverse))
            time_to_mfe=(favorable.index(max(favorable))+1) if raw_mfe>0 else None
            direction=1 if s=="LONG" else -1
            end_return=close_returns[-1]*direction
            side[s]={
                "mfe_bps":raw_mfe,"mae_bps":raw_mae,
                "time_to_mfe_minutes":time_to_mfe,
                "close_return_bps":end_return,
                "giveback_from_mfe_bps":max(0.0,raw_mfe-end_return),
                "path_smoothness_ratio":abs(end_return)/total_path if total_path>0 else None,
                "remaining_favorable_after_half_horizon_bps":
                   max(0.0,max(favorable[h//2:])) if h//2<h else None,
                "hit_target_before_adverse":{
                    str(int(t)):_first_before(favorable,adverse,float(t),float(adverse_bps))
                    for t in target_bps
                },
                "note":"Future candle extrema are labels only, not executable fills",
            }
        report["horizons"][str(h)]=side
    return report
