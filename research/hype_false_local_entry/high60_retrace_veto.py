"""HIGH-only +60m retrace confirmation for frozen HARD120 primary.

Research/paper only. It does not alter INTERNAL_HARD120_CHECKPOINT_V2.
A HIGH primary can be mirrored into the veto-stack only when the first completed
M1 close at/after +60 minutes has retraced at least 50 bps from the candidate
HIGH. Threshold was frozen after Jul/Aug + Oct/Nov inspection and must be
validated on later untouched/forward periods.
"""
from __future__ import annotations
from typing import Iterable, Mapping, Optional

AGE_S=3600
MIN_HIGH_RETRACE_60_BPS=50.0


def sample_retrace60(*, side:str, candidate_ts_ms:int, extreme_price:float,
                     completed_m1_rows:Iterable[Mapping], observed_ms:int)->Optional[dict]:
    target=int(candidate_ts_ms)+AGE_S*1000
    best=None
    for r in completed_m1_rows:
        end=int(r.get("bar_end_ms") or r.get("ts_ms") or 0)
        if end<target or end>int(observed_ms):
            continue
        try: close=float(r["close"])
        except Exception: continue
        if close<=0: continue
        if best is None or end<best["sample_ts_ms"]:
            best={"sample_ts_ms":end,"mark_price":close}
    if best is None:
        return None
    p=float(extreme_price); mark=float(best["mark_price"]); side=str(side).upper()
    retrace=((p/mark-1.0) if side=="HIGH" else (mark/p-1.0))*10_000.0 if p>0 else 0.0
    return {**best,"target_ts_ms":target,"retrace_60_bps":retrace}


def high_primary_confirmed(*, side:str, sample:Optional[Mapping])->tuple[bool,dict]:
    if str(side).upper()!="HIGH":
        return True,{"ready":True,"applies":False,"reason":"LOW_primary_unmodified"}
    retr=None if sample is None else float(sample.get("retrace_60_bps") or 0.0)
    ready=retr is not None and retr>=MIN_HIGH_RETRACE_60_BPS
    return bool(ready),{
        "ready":bool(ready),"applies":True,
        "retrace_60_bps":retr,
        "min_retrace_60_bps":MIN_HIGH_RETRACE_60_BPS,
        "sample_ts_ms":None if sample is None else int(sample.get("sample_ts_ms") or 0),
    }


def contract()->dict:
    return {
        "name":"HARD120_HIGH60_RETRACE_VETO_SHADOW_V1",
        "role":"HIGH_PRIMARY_CONFIRMATION_SHADOW_ONLY",
        "side":"HIGH",
        "age_s":AGE_S,
        "min_high_retrace_60_bps":MIN_HIGH_RETRACE_60_BPS,
        "primary_contract_unchanged":True,
        "core_flip_authorized":False,
        "historical_status":"FROZEN_AFTER_JULAUG_OCTNOV_AWAITING_UNTOUCHED_SEPTEMBER",
        "promotion":"FORWARD_SCORE_ONLY",
    }
