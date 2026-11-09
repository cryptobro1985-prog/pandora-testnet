from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Mapping, Optional


CHECKPOINTS_S = (30, 60, 90, 180, 300)


class ConfirmState(str, Enum):
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    PROBABLE = "PROBABLE"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class ConfirmationEvidence:
    """Causal evidence available at one checkpoint after an observed extreme.

    All values must be computed only from data received no later than ts_ms.
    No H1/K2 teacher state, future candle, future terminality label or TARGET_ID
    may be supplied here.
    """

    ts_ms: int
    side: str
    extreme_ts_ms: int
    extreme_price: float
    price: float
    reversal_return_bps: float
    flow_efficiency: float
    opposing_impact_efficiency: float
    same_side_liq_decay: float
    book_recovery: float
    oi_price_agreement: float = 0.0
    no_new_extreme: bool = True
    data_quality_ok: bool = True

    @property
    def age_s(self) -> float:
        return max(0.0, (self.ts_ms - self.extreme_ts_ms) / 1000.0)


@dataclass(frozen=True)
class ConfirmationDecision:
    state: ConfirmState
    confidence: float
    checkpoint_s: int
    enter: bool
    target_side: Optional[str]
    reason: str
    score: float
    invalidation_price: float


@dataclass
class CandidateTracker:
    side: str
    extreme_ts_ms: int
    extreme_price: float
    highest_state: ConfirmState = ConfirmState.CANDIDATE
    first_confirm_ts_ms: Optional[int] = None
    decisions: list[ConfirmationDecision] = field(default_factory=list)


class TimeToConfirmationEngine:
    """Research/paper-only early terminal-local confirmation engine.

    The objective is not to promise 100% future precision. It minimizes
    time-to-confirmation subject to frozen precision constraints.

    Design:
    - LOW and HIGH are symmetric but independently calibratable.
    - New same-side extremes invalidate the previous candidate immediately.
    - Confidence can rise only as fresh causal evidence arrives.
    - CONFIRMED is the earliest point at which a paper-direction authorization
      may be emitted. Real order placement is intentionally absent.
    """

    def __init__(
        self,
        confirm_threshold: float = 0.86,
        probable_threshold: float = 0.70,
        checkpoint_thresholds: Optional[Mapping[int, float]] = None,
    ):
        self.confirm_threshold = float(confirm_threshold)
        self.probable_threshold = float(probable_threshold)
        self.checkpoint_thresholds = dict(checkpoint_thresholds or {
            30: 0.94,
            60: 0.91,
            90: 0.89,
            180: 0.87,
            300: 0.86,
        })
        self.active: dict[str, Optional[CandidateTracker]] = {"LOW": None, "HIGH": None}

    @staticmethod
    def _target_side(side: str) -> str:
        return "LONG" if side == "LOW" else "SHORT"

    @staticmethod
    def _checkpoint(age_s: float) -> int:
        eligible = [x for x in CHECKPOINTS_S if age_s >= x]
        return eligible[-1] if eligible else 0

    @staticmethod
    def _score(x: ConfirmationEvidence) -> float:
        # Causal transition signature from the frozen research handoff:
        # price response -> flow efficiency -> liquidation exhaustion ->
        # book recovery / transfer -> OI+price agreement.
        #
        # Inputs are normalized so that roughly 1.0 means strong confirming
        # evidence and <=0 means contrary evidence. The weights are intentionally
        # simple/frozen; historical calibration is done outside this class.
        parts = (
            (0.30, x.reversal_return_bps / 35.0),
            (0.20, x.flow_efficiency / 0.010),
            (0.15, -x.opposing_impact_efficiency / 0.010),
            (0.15, x.same_side_liq_decay),
            (0.15, x.book_recovery),
            (0.05, x.oi_price_agreement),
        )
        z = 0.0
        for w, v in parts:
            if not isfinite(float(v)):
                return 0.0
            z += w * max(-1.0, min(1.5, float(v)))
        # Map useful range to [0, 1] without pretending to be a calibrated
        # probability. Calibration/reliability is reported separately.
        return max(0.0, min(1.0, 0.5 + 0.5 * z))

    def start_or_extend(self, side: str, ts_ms: int, extreme_price: float) -> CandidateTracker:
        side = side.upper()
        if side not in self.active:
            raise ValueError("side must be LOW or HIGH")
        if not isfinite(extreme_price) or extreme_price <= 0:
            raise ValueError("extreme_price must be finite and positive")
        old = self.active[side]
        extends = old is None or (
            side == "LOW" and extreme_price < old.extreme_price
        ) or (
            side == "HIGH" and extreme_price > old.extreme_price
        )
        if extends:
            tracker = CandidateTracker(side=side, extreme_ts_ms=int(ts_ms), extreme_price=float(extreme_price))
            self.active[side] = tracker
            return tracker
        return old

    def evaluate(self, x: ConfirmationEvidence) -> ConfirmationDecision:
        side = x.side.upper()
        if side not in self.active:
            raise ValueError("side must be LOW or HIGH")
        if x.price <= 0 or x.extreme_price <= 0:
            raise ValueError("prices must be positive")

        tracker = self.active.get(side)
        if tracker is None:
            tracker = self.start_or_extend(side, x.extreme_ts_ms, x.extreme_price)

        # Any fresh same-side extension kills the previous hypothesis. This is
        # the key false-local protection that allows earlier confirmation.
        broken = (
            (side == "LOW" and x.price < tracker.extreme_price) or
            (side == "HIGH" and x.price > tracker.extreme_price) or
            (not x.no_new_extreme)
        )
        if broken:
            d = ConfirmationDecision(
                ConfirmState.INVALIDATED, 0.0, self._checkpoint(x.age_s), False,
                None, "new same-side extreme invalidated candidate", 0.0,
                tracker.extreme_price,
            )
            tracker.highest_state = ConfirmState.INVALIDATED
            tracker.decisions.append(d)
            self.active[side] = CandidateTracker(
                side=side, extreme_ts_ms=x.ts_ms, extreme_price=x.price
            )
            return d

        cp = self._checkpoint(x.age_s)
        if not x.data_quality_ok:
            d = ConfirmationDecision(
                ConfirmState.WATCH, 0.0, cp, False, None,
                "data quality gate failed", 0.0, tracker.extreme_price,
            )
            tracker.decisions.append(d)
            return d

        score = self._score(x)
        threshold = self.checkpoint_thresholds.get(cp, self.confirm_threshold)

        if cp == 0:
            state = ConfirmState.CANDIDATE
            enter = False
            reason = "waiting for first causal checkpoint"
        elif score >= threshold:
            state = ConfirmState.CONFIRMED
            enter = True
            reason = f"earliest frozen checkpoint cleared ({cp}s)"
        elif score >= self.probable_threshold:
            state = ConfirmState.PROBABLE
            enter = False
            reason = f"probable reversal; confirmation threshold not cleared at {cp}s"
        else:
            state = ConfirmState.CANDIDATE
            enter = False
            reason = f"candidate survives but evidence is insufficient at {cp}s"

        confidence = score
        d = ConfirmationDecision(
            state, confidence, cp, enter,
            self._target_side(side) if enter else None,
            reason, score, tracker.extreme_price,
        )
        tracker.decisions.append(d)
        if state == ConfirmState.CONFIRMED and tracker.first_confirm_ts_ms is None:
            tracker.first_confirm_ts_ms = x.ts_ms
        if state in (ConfirmState.PROBABLE, ConfirmState.CONFIRMED):
            tracker.highest_state = state
        return d


def confirmation_metrics(extreme_price: float, entry_price: float, side: str, delay_s: float) -> dict:
    """Metrics used by replay/OOS selection: delay and move surrendered."""
    if extreme_price <= 0 or entry_price <= 0:
        raise ValueError("prices must be positive")
    side = side.upper()
    if side == "LOW":
        missed_bps = (entry_price / extreme_price - 1.0) * 10000.0
    elif side == "HIGH":
        missed_bps = (extreme_price / entry_price - 1.0) * 10000.0
    else:
        raise ValueError("side must be LOW or HIGH")
    return {
        "confirmation_delay_s": float(delay_s),
        "missed_move_bps": max(0.0, float(missed_bps)),
    }
