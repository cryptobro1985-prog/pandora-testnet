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
    def __init__(self):
        self.bars = deque(maxlen=400)
        self.last_ts = None
        self.active = {"LOW": "WATCH", "HIGH": "WATCH"}
        self.core_side = None
        self.anchor = {"LOW": None, "HIGH": None}
        self.events = []

    def on_bar(self, bar):
        ts = int(bar["ts_ms"])
        end = int(bar.get("bar_end_ms") or ts + int(bar.get("interval_ms", 60000)))
        if self.last_ts is not None and end <= self.last_ts:
            raise ValueError("bar must be completed and strictly chronological")
        self.last_ts = end
        high, low, close = (float(bar[k]) for k in ("high", "low", "close"))
        if not all(isfinite(v) for v in (high, low, close)) or not 0 < low <= close <= high:
            raise ValueError("invalid OHLC")
        self.bars.append({"end": end, "high": high, "low": low, "close": close,
                          "buy": max(0., float(bar.get("buy_notional", 0))),
                          "sell": max(0., float(bar.get("sell_notional", 0)))})
        if len(self.bars) < 30:
            return []
        arr = list(self.bars)
        out = []
        for side in ("LOW", "HIGH"):
            sgn = 1 if side == "LOW" else -1
            # Rolling anchor from past/completed bars only; resets if a new
            # extreme appears. Never assume the anchor is a true H1 local.
            anchor = min(x["low"] for x in arr[-30:]) if sgn == 1 else max(x["high"] for x in arr[-30:])
            if self.anchor[side] is None or (sgn == 1 and anchor < self.anchor[side]) or (sgn == -1 and anchor > self.anchor[side]):
                self.active[side] = "WATCH"
            self.anchor[side] = anchor
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
                flip = stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED") and self.core_side != side
                if flip:
                    self.core_side = side
                ev = Signal(end, side, stage, score, anchor, close, flip)
                self.events.append(ev)
                out.append(ev)
            self.active[side] = stage
        return out
