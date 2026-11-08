"""Regime gate V2 for the HIGH-flow HARD120 shadow.

Selected after analysing Jul/Aug, Sep, and Oct/Nov, and frozen BEFORE the sealed
late-August tape is scored.

The original HIGH-flow shadow requires seller-dominated first-15m flow in a
narrow HARD120 retrace-fraction band. V2 adds two causal structural-quality
checks that are known by the +120m decision time:

1) the 180 completed minutes before the candidate must show an upward
   directional return at least 10x the realized 60m M1 return volatility;
2) the completed candidate minute must span at least 10 bps.

Rationale: a terminal HIGH is more credible when seller flow arrives after a
mature, directional advance and a non-trivial terminal extreme, rather than
inside a noisy/choppy or microscopic local fluctuation.

Research/paper only. Primary HARD120 is unchanged. No core flip authorization.
"""
from __future__ import annotations
from math import sqrt
from typing import Iterable, Mapping

MIN_TREND_TO_VOL=10.0
MIN_CANDIDATE_RANGE_BPS=10.0


def _bar_times(row:Mapping)->tuple[int,int]:
    interval=int(row.get("interval_ms",60_000) or 60_000)
    end=int(row.get("bar_end_ms") or row.get("ts_ms") or 0)
    if row.get("start_ms") is not None:
        start=int(row["start_ms"])
    else:
        ts=int(row.get("ts_ms") or 0)
        start=ts-interval if end==ts else ts
    return start,end


def regime_metrics(*, candidate_ts_ms:int, completed_m1_rows:Iterable[Mapping])->dict:
    rows=[]
    candidate_bar=None
    ts=int(candidate_ts_ms)
    for r in completed_m1_rows:
        start,end=_bar_times(r)
        if end<=ts:
            rows.append(r)
        if start<=ts<end:
            candidate_bar=r
    if candidate_bar is None or len(rows)<180:
        return {
            "ready":False,"reason":"insufficient_causal_m1_history",
            "prehistory_bars":len(rows),
        }

    pre180=rows[-180:]
    pre60=rows[-60:]
    first_open=float(pre180[0]["open"])
    last_close=float(pre180[-1]["close"])
    pre_ret180_bps=((last_close/first_open)-1.0)*10_000.0 if first_open>0 else 0.0

    rets=[]
    for a,b in zip(pre60,pre60[1:]):
        ca=float(a["close"]);cb=float(b["close"])
        if ca>0: rets.append((cb/ca-1.0)*10_000.0)
    if not rets:
        vol60=0.0
    else:
        mean=sum(rets)/len(rets)
        vol60=sqrt(sum((x-mean)**2 for x in rets)/len(rets))

    lo=float(candidate_bar["low"]);hi=float(candidate_bar["high"])
    candidate_range_bps=(hi/lo-1.0)*10_000.0 if lo>0 else 0.0
    trend_to_vol=max(0.0,pre_ret180_bps)/max(vol60,1e-12)

    checks={
        "mature_directional_advance":trend_to_vol+1e-12>=MIN_TREND_TO_VOL,
        "nontrivial_candidate_minute":candidate_range_bps+1e-12>=MIN_CANDIDATE_RANGE_BPS,
    }
    return {
        "ready":all(checks.values()),
        "checks":checks,
        "pre_ret180_bps":pre_ret180_bps,
        "pre_vol60_bps":vol60,
        "trend_to_vol":trend_to_vol,
        "min_trend_to_vol":MIN_TREND_TO_VOL,
        "candidate_range_bps":candidate_range_bps,
        "min_candidate_range_bps":MIN_CANDIDATE_RANGE_BPS,
        "prehistory_bars":len(rows),
    }


def contract()->dict:
    return {
        "name":"HARD120_HIGH_FLOW_REGIME_GATE_V2",
        "role":"HIGH_FLOW_SHADOW_REGIME_CONFIRMATION",
        "min_trend_to_vol":MIN_TREND_TO_VOL,
        "min_candidate_range_bps":MIN_CANDIDATE_RANGE_BPS,
        "feature_definition":{
            "trend_to_vol":"max(0, 180m completed-M1 directional return bps) / population std of prior-60m M1 close returns bps",
            "candidate_range_bps":"completed candidate-minute high/low range",
        },
        "selection_periods":["2026-07-12..2026-08-07","2026-09-01..2026-10-01","2026-10-04..2026-11-03"],
        "sealed_validation_period_not_scored_when_frozen":"2026-08-08..2026-09-01",
        "primary_contract_unchanged":True,
        "core_flip_authorized":False,
        "promotion":"SEALED_PERIOD_THEN_FORWARD_ONLY",
    }
