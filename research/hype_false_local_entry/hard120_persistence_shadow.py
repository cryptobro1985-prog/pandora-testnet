"""HARD120 reversal-persistence challenger.

Frozen development rule, selected BEFORE inspecting the September 2026 holdout.

The primary HARD120 signal remains unchanged and continues to be logged. This
challenger asks one extra causal question at the same +120m checkpoint:

    how much of the strongest reversal excursion seen since the candidate is
    still held by the checkpoint close?

False corrections often spike away from the extreme, then fade back toward the
old trend before +120m. Terminal reversals tend to retain more of the reversal.

Research/paper only. Never authorizes a core flip.
"""
from __future__ import annotations

from typing import Iterable, Mapping

MIN_PERSISTENCE=0.65


def persistence_metrics(*, side:str, extreme_price:float, retrace_bps:float,
                        candidate_ts_ms:int, sample_ts_ms:int,
                        completed_m1_rows:Iterable[Mapping])->dict:
    side=str(side).upper()
    p=float(extreme_price)
    if side not in {"LOW","HIGH"} or p<=0:
        return {"ready":False,"reason":"invalid_candidate"}

    rows=[]
    for r in completed_m1_rows:
        end=int(r.get("bar_end_ms") or 0)
        if int(candidate_ts_ms)<end<=int(sample_ts_ms):
            rows.append(r)
    if not rows:
        return {"ready":False,"reason":"no_completed_path"}

    if side=="LOW":
        best=max(float(r["high"]) for r in rows)
        max_reversal_bps=max(0.0,(best/p-1.0)*10_000.0)
    else:
        best=min(float(r["low"]) for r in rows)
        max_reversal_bps=max(0.0,(p/best-1.0)*10_000.0)

    retr=max(0.0,float(retrace_bps))
    ratio=retr/max(max_reversal_bps,1e-12)
    ratio=max(0.0,min(1.0,ratio))
    return {
        "ready":ratio+1e-12>=MIN_PERSISTENCE,
        "retrace_bps":retr,
        "max_reversal_bps":max_reversal_bps,
        "reversal_persistence":ratio,
        "min_reversal_persistence":MIN_PERSISTENCE,
        "path_bars":len(rows),
    }


def contract()->dict:
    return {
        "name":"HARD120_REVERSAL_PERSISTENCE_SHADOW_V1",
        "role":"SHADOW_FILTERED_STACK_ONLY",
        "checkpoint":"same frozen HARD120 +120m completed-M1 checkpoint",
        "min_reversal_persistence":MIN_PERSISTENCE,
        "definition":"checkpoint retrace / maximum causal reversal excursion since candidate",
        "primary_contract_unchanged":True,
        "core_flip_authorized":False,
        "development_periods":["2026-07-12..2026-08-07","2026-10-04..2026-11-03"],
        "holdout_not_inspected_when_frozen":"2026-09-01..2026-10-01",
        "promotion":"FORWARD_SCORE_ONLY",
    }
