"""Research-only one-shot HYPE H1 local gate; never executes orders.
Frozen age=285 minutes; minute snapshots may arrive within a predeclared 60s
tolerance. A checkpoint may not be retried after failure/missing data.
"""
from dataclasses import dataclass
from typing import Literal

Side = Literal["LOW", "HIGH"]
CHECKPOINT_MS = 285 * 60_000
GRACE_MS = 60_000
MIN_BPS = 130.0
REL_FRACTION = {"LOW": 0.80, "HIGH": 0.75}

@dataclass
class Candidate:
    side: Side
    extreme_ts_ms: int
    extreme_price: float
    pre_move_180_bps: float
    consumed: bool = False
    lineage: int = 0

def extend(c: Candidate, ts_ms: int, px: float, pre_move_bps: float) -> Candidate:
    more = px < c.extreme_price if c.side == "LOW" else px > c.extreme_price
    if more and ts_ms >= c.extreme_ts_ms:
        return Candidate(c.side, ts_ms, px, pre_move_bps, lineage=c.lineage + 1)
    return c

def observe(c: Candidate, ts_ms: int, px: float, *, snapshot_available_ts_ms: int | None = None) -> str:
    """Consume checkpoint exactly once; return WAIT/TRUE/FALSE/MISSED."""
    if c.consumed:
        return "WAIT"
    check = c.extreme_ts_ms + CHECKPOINT_MS
    if ts_ms < check:
        return "WAIT"
    c.consumed = True
    avail = ts_ms if snapshot_available_ts_ms is None else snapshot_available_ts_ms
    if ts_ms > check + GRACE_MS or avail > check + GRACE_MS or avail < check:
        return "MISSED"
    if not c.extreme_price > 0 or not px > 0 or not c.pre_move_180_bps > 0:
        return "MISSED"
    bps = (px / c.extreme_price - 1) * 10_000 if c.side == "LOW" else (c.extreme_price / px - 1) * 10_000
    return "TRUE" if bps >= MIN_BPS and bps / c.pre_move_180_bps >= REL_FRACTION[c.side] else "FALSE"
