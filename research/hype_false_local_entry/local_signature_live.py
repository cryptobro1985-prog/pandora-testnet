from __future__ import annotations

import math
from typing import Any

from research.hype_local_only.live_features import live_to_archive_features
from research.hype_quant.feature_contract import INPUT_IDS


def _finite(v: Any) -> bool:
    return isinstance(v,(int,float)) and math.isfinite(float(v))


def _mean(values):
    q=[float(x) for x in values if _finite(x)]
    return sum(q)/len(q) if q else 0.0


def _fresh_quality(state, coverage: dict) -> bool:
    # Quality is causal and evaluated at the current state. Missing rich inputs
    # do not become numeric zero evidence.
    if getattr(state,"book_bids",None) and getattr(state,"book_asks",None):
        try:
            if max(float(x) for x in state.book_bids) >= min(float(x) for x in state.book_asks):
                return False
        except Exception:
            return False
    if int(getattr(state,"receipt_sequence_gaps",0) or 0) < 0:
        return False
    ages=coverage.get("point_age_seconds") or {}
    # Raw timestamps / continuity / collector health must have been observed.
    for pid in (77,78,79,80,116):
        if str(pid) in ages and ages[str(pid)] is not None and float(ages[str(pid)])>600:
            return False
    return True


def _evidence_summary(side: str, fx: dict[str,float]) -> dict[str,float]:
    """Human-readable causal signature components, not a fixed rule gate."""
    rev=1.0 if side=="LOW" else -1.0

    new_eff=[]
    old_eff=[]
    price_response=[]
    flow=[]
    for w in (5,15,30,60,180,300):
        a=fx.get(f"rev_eff_{w}s")
        b=fx.get(f"old_eff_{w}s")
        r=fx.get(f"rev_ret_{w}s")
        f=fx.get(f"rev_flow_{w}s")
        if _finite(a):new_eff.append(float(a)/1e6)
        if _finite(b):old_eff.append(float(b)/1e6)
        if _finite(r):price_response.append(float(r))
        if _finite(f):flow.append(float(f))

    book=[
        fx.get("discovery__book_depth_imbalance_5_rev"),
        fx.get("discovery__book_depth_imbalance_10_rev"),
        fx.get("discovery__book_depth_imbalance_25_rev"),
        fx.get("discovery__book_depth_imbalance_50_rev"),
        fx.get("discovery__book_add_imbalance_15s_rev"),
        fx.get("discovery__book_add_imbalance_60s_rev"),
        fx.get("discovery__book_cancel_pressure_15s_rev"),
        fx.get("discovery__book_cancel_pressure_60s_rev"),
    ]
    liq=[
        fx.get("discovery__liq_capitulation_rev_15s"),
        fx.get("discovery__liq_capitulation_rev_60s"),
        fx.get("discovery__liq_capitulation_rev_180s"),
        fx.get("discovery__liq_capitulation_rev_300s"),
    ]
    oi=[
        fx.get("discovery__live_oi_x_return_60s"),
        fx.get("discovery__live_oi_x_return_180s"),
        fx.get("discovery__live_oi_x_return_300s"),
        fx.get("discovery__live_oi_x_flow_60s"),
        fx.get("discovery__live_oi_x_flow_180s"),
        fx.get("discovery__live_oi_x_flow_300s"),
    ]

    return {
        "retrace_bps":float(fx.get("retrace_bps",0.0) or 0.0),
        "new_side_efficiency":_mean(new_eff),
        "old_side_efficiency":_mean(old_eff),
        "efficiency_transfer":_mean(new_eff)-_mean(old_eff),
        "price_response_new_side":_mean(price_response),
        "flow_new_side":_mean(flow),
        "book_transfer_to_new_side":_mean(book),
        "liquidation_exhaustion_or_capitulation":_mean(liq),
        "oi_price_flow_relation":_mean(oi),
        "reversal_attempts":float(fx.get("reversal_attempts",0.0) or 0.0),
        "orientation":rev,
    }


def build_signature_state(*, side: str, candidate, ts_ms: int, price: float,
                          x: dict[str,Any], state) -> tuple[dict[str,float],dict]:
    age_s=max(0.0,(int(ts_ms)-int(candidate.extreme_ts_ms))/1000.0)
    fx=live_to_archive_features(
        side,age_s,float(candidate.extreme_price),float(price),x,state
    )
    coverage=state.coverage_report()

    # Availability/freshness are causal features. They allow the model to learn
    # that an apparent signature with stale/missing inputs is less trustworthy.
    ages=coverage.get("point_age_seconds") or {}
    seen=set(coverage.get("seen_input_ids") or [])
    for pid in sorted(INPUT_IDS):
        fx[f"contract__p{pid:03d}_seen"]=1.0 if pid in seen else 0.0
        age=ages.get(str(pid))
        if _finite(age):
            fx[f"contract__p{pid:03d}_age_s"]=float(age)
    fx["contract__input_coverage"]=len(seen&set(INPUT_IDS))/max(1,len(INPUT_IDS))

    evidence=_evidence_summary(side,fx)
    meta={
        "seen_input_ids":sorted(seen&set(INPUT_IDS)),
        "seen_input_count":len(seen&set(INPUT_IDS)),
        "input_contract_count":len(INPUT_IDS),
        "input_coverage":fx["contract__input_coverage"],
        "quality_ok":_fresh_quality(state,coverage),
        "evidence":evidence,
        "age_s_metric_only":age_s,
    }
    return fx,meta
