"""Causal sequential HYPE turning-state engine; PAPER ONLY.

No label, future candle, K2, or future outcome enters on_bar().
One observation per completed M1 bar. EARLY/CONFIRMED never flips core.
Thresholds are research defaults, not OOS validated.
"""
from collections import deque
from dataclasses import dataclass
from math import isfinite

STAGES = ("WATCH", "FORMING", "EARLY_PROBE", "CONFIRMED",
          "HARD_CONFIRMED", "ULTRA_CONFIRMED")
RANK = {name: i for i, name in enumerate(STAGES)}

@dataclass(frozen=True)
class Signal:
    ts_ms: int
    side: str
    stage: str
    score: int
    extreme_price: float
    close: float
    core_flip: bool

class CausalReversalMachine:
    def __init__(self, reset_anchors_on_flip=True):
        self.reset_anchors_on_flip = reset_anchors_on_flip
        self.bars = deque(maxlen=400)
        self.last_ts = None
        self.active = {"LOW": "WATCH", "HIGH": "WATCH"}
        self.core_side = None
        self.anchor = {"LOW": None, "HIGH": None}
        self.anchor_end = {"LOW": None, "HIGH": None}
        self.events = []

    def on_bar(self, bar):
        interval = int(bar.get("interval_ms", 60000))
        explicit_end = bar.get("bar_end_ms")
        if bar.get("start_ms") is not None:
            start = int(bar["start_ms"])
        else:
            ts = int(bar["ts_ms"])
            # Canonical compact_1m.ts_ms is the completed candle END.
            # Match dense_causal_reachability and first_flip_path_audit.
            # Start-stamped alternative inputs must explicitly set start_ms.
            start = int(explicit_end) - interval if explicit_end is not None else ts - interval
        end = int(explicit_end if explicit_end is not None else start + interval)
        if self.last_ts is not None and end <= self.last_ts:
            raise ValueError("bar must be completed and strictly chronological")
        if end <= start or (self.last_ts is not None and start < self.last_ts):
            raise ValueError("overlapping or incomplete M1 bar")
        high, low, close = (float(bar[k]) for k in ("high", "low", "close"))
        if not all(isfinite(v) for v in (high, low, close)) or not 0 < low <= close <= high:
            raise ValueError("invalid OHLC")
        self.last_ts = end
        self.bars.append({"end": end, "high": high, "low": low, "close": close,
                          "buy": max(0., float(bar.get("buy_notional", 0))),
                          "sell": max(0., float(bar.get("sell_notional", 0)))})
        if len(self.bars) < 30:
            return []
        arr = list(self.bars)
        out = []
        flipped_this_bar = False
        for side in ("LOW", "HIGH"):
            sgn = 1 if side == "LOW" else -1
            # Keep the candidate extreme until a genuinely more extreme
            # completed bar appears. Rolling-window expiry must never move
            # an anchor forward or manufacture a fresh reversal.
            observed = low if sgn == 1 else high
            previous = self.anchor[side]
            is_new = previous is None or (sgn == 1 and observed < previous) or (sgn == -1 and observed > previous)
            if is_new:
                self.anchor[side] = observed
                self.anchor_end[side] = end
                self.active[side] = "WATCH"
            anchor = self.anchor[side]
            retrace_bps = sgn * (close / anchor - 1) * 10000
            move3_bps = sgn * (close / arr[-4]["close"] - 1) * 10000
            move5_bps = sgn * (close / arr[-6]["close"] - 1) * 10000
            buys = sum(x["buy"] for x in arr[-3:])
            sells = sum(x["sell"] for x in arr[-3:])
            flow = sgn * (buys - sells) / max(1e-12, buys + sells)
            # Structure: close crosses beyond previous completed three-bar range.
            prior = arr[-4:-1]
            break3 = close > max(x["high"] for x in prior) if sgn == 1 else close < min(x["low"] for x in prior)
            old_side_failed = (min(x["low"] for x in arr[-3:]) > anchor if sgn == 1
                               else max(x["high"] for x in arr[-3:]) < anchor)
            score = sum((retrace_bps >= 12, move3_bps >= 8, move5_bps >= 12,
                         flow >= 0.08, break3, old_side_failed))
            if score >= 6 and retrace_bps >= 25 and old_side_failed and break3:
                stage = "ULTRA_CONFIRMED"
            elif score >= 5 and retrace_bps >= 20 and old_side_failed:
                stage = "HARD_CONFIRMED"
            elif score >= 4 and retrace_bps >= 12:
                stage = "CONFIRMED"
            elif score >= 3:
                stage = "EARLY_PROBE"
            elif score >= 2:
                stage = "FORMING"
            else:
                stage = "WATCH"
            if RANK[stage] > RANK[self.active[side]]:
                flip = (not flipped_this_bar and
                        stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED") and
                        self.core_side != side)
                if flip:
                    self.core_side = side
                    flipped_this_bar = True
                ev = Signal(end, side, stage, score, anchor, close, flip)
                self.events.append(ev)
                out.append(ev)
            self.active[side] = stage
        # A confirmed reversal begins a fresh structural leg. Reset anchors
        # after evaluating both sides, allowing nested H1 turns.
        if self.reset_anchors_on_flip and any(event.core_flip for event in out):
            self.anchor = {"LOW": low, "HIGH": high}
            self.anchor_end = {"LOW": end, "HIGH": end}
            self.active = {"LOW": "WATCH", "HIGH": "WATCH"}
        return out
