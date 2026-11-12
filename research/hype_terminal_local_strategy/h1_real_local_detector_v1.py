"""HYPE strict-H1 real-local detector V1.

Research/shadow only. No live-order authorization.
The rule was frozen from the 2026-11-12 strict H1 audit.

Important:
- Strict H1 labels are offline teacher/scoring only.
- Live code must maintain one active H1 hypothesis per side.
- Same-side more-extreme extension resets the candidate lineage.
- Missing rich microstructure does not block this V1 rule because unstable rich
  thresholds were intentionally not promoted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["LOW", "HIGH"]

RULES = {
    "LOW": {
        "age_minutes": 285,
        "min_retrace_bps": 130.0,
        "min_retrace_fraction_pre_180": 0.80,
    },
    "HIGH": {
        "age_minutes": 285,
        "min_retrace_bps": 130.0,
        "min_retrace_fraction_pre_180": 0.75,
    },
}

@dataclass
class H1Candidate:
    side: Side
    extreme_ts_ms: int
    extreme_price: float
    pre_move_180_bps: float

def is_more_extreme(side: Side, new_price: float, old_price: float) -> bool:
    return new_price < old_price if side == "LOW" else new_price > old_price

def retrace_bps(side: Side, extreme_price: float, mark_price: float) -> float:
    if extreme_price <= 0 or mark_price <= 0:
        return float("-inf")
    if side == "LOW":
        return (mark_price / extreme_price - 1.0) * 10_000.0
    return (extreme_price / mark_price - 1.0) * 10_000.0

def evaluate(candidate: H1Candidate, now_ms: int, mark_price: float) -> dict:
    rule = RULES[candidate.side]
    age_minutes = max(0.0, (int(now_ms) - int(candidate.extreme_ts_ms)) / 60_000.0)
    retr = retrace_bps(candidate.side, candidate.extreme_price, mark_price)
    frac = retr / max(float(candidate.pre_move_180_bps), 1e-12)

    checkpoint_ready = age_minutes >= float(rule["age_minutes"])
    confirmed = (
        checkpoint_ready
        and retr >= float(rule["min_retrace_bps"])
        and frac >= float(rule["min_retrace_fraction_pre_180"])
    )
    return {
        "state": "TRUE" if confirmed else "WAIT",
        "side": candidate.side,
        "age_minutes": age_minutes,
        "retrace_bps": retr,
        "retrace_fraction_pre_180": frac,
        "rule": dict(rule),
    }

def on_same_side_extension(candidate: H1Candidate, new_ts_ms: int, new_price: float,
                           new_pre_move_180_bps: float) -> H1Candidate:
    if not is_more_extreme(candidate.side, float(new_price), float(candidate.extreme_price)):
        return candidate
    return H1Candidate(
        side=candidate.side,
        extreme_ts_ms=int(new_ts_ms),
        extreme_price=float(new_price),
        pre_move_180_bps=float(new_pre_move_180_bps),
    )
