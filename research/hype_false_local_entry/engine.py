from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ReversalState(str, Enum):
    WATCH = "WATCH"
    FORMING = "FORMING"
    EARLY_CONFIRM = "EARLY_CONFIRM"
    CONFIRMED = "CONFIRMED"
    HARD_CONFIRMED = "HARD_CONFIRMED"


@dataclass
class ReversalConfig:
    # Research seeds from the 30D HYPE study. Recalibrate walk-forward before live use.
    min_swing_atr_watch: float = 2.0
    min_survival_s_forming: int = 180
    min_survival_s_early: int = 600

    retrace_fraction_soft: float = 0.08
    retrace_fraction_strong: float = 0.12
    rev_return_300s_soft: float = 0.0010

    early_score: float = 7.0
    confirm_score: float = 9.0
    hard_score: float = 10.5
    persistence_updates: int = 2


@dataclass
class ReversalSnapshot:
    side: str
    survival_s: float
    swing_atr_mult: float
    retrace_fraction: float

    rev_return_300s: float
    rev_flow_180s: float
    rev_eff_180s: float
    old_eff_180s: float

    macd_hist_rev: float
    macd_slope3_rev: float

    oi_notional_delta_rev: Optional[float] = None
    same_side_extreme_broken: bool = False


@dataclass
class ReversalDecision:
    state: ReversalState
    score: float
    reason: str
    paper_fraction_of_intended_position: float


class HypeFalseLocalEntryEngine:
    """
    Research / paper-only reversal state machine.

    Core principle:
    - never predict the exact extreme;
    - candidate is immediately invalidated by a new same-side extreme;
    - accumulate causal evidence that the old side lost price impact and
      the opposite side is accepting price;
    - use staged confidence instead of one binary local flag.

    paper_fraction_of_intended_position is a research replay variable,
    not a real-money sizing recommendation.
    """

    def __init__(self, config: ReversalConfig | None = None) -> None:
        self.cfg = config or ReversalConfig()
        self.state = ReversalState.WATCH
        self._confirm_streak = 0

    def reset(self) -> None:
        self.state = ReversalState.WATCH
        self._confirm_streak = 0

    def _score(self, x: ReversalSnapshot) -> float:
        s = 0.0

        if x.swing_atr_mult >= self.cfg.min_swing_atr_watch:
            s += 1.0
        if x.swing_atr_mult >= 2.5:
            s += 1.0

        if x.survival_s >= self.cfg.min_survival_s_forming:
            s += 1.0
        if x.retrace_fraction >= self.cfg.retrace_fraction_soft:
            s += 1.5
        if x.retrace_fraction >= self.cfg.retrace_fraction_strong:
            s += 1.5

        if x.rev_return_300s >= self.cfg.rev_return_300s_soft:
            s += 1.0

        if x.rev_flow_180s > 0:
            s += 0.75
        if x.rev_eff_180s > x.old_eff_180s:
            s += 1.5

        if x.macd_hist_rev > 0:
            s += 0.75
        if x.macd_slope3_rev > 0:
            s += 0.75

        if x.oi_notional_delta_rev is not None and x.oi_notional_delta_rev > 0:
            s += 0.5

        return s

    def update(self, x: ReversalSnapshot) -> ReversalDecision:
        if x.same_side_extreme_broken:
            self.reset()
            return ReversalDecision(
                state=self.state,
                score=0.0,
                reason="INVALIDATED_NEW_SAME_SIDE_EXTREME",
                paper_fraction_of_intended_position=0.0,
            )

        score = self._score(x)

        if x.swing_atr_mult < self.cfg.min_swing_atr_watch:
            self.state = ReversalState.WATCH
            self._confirm_streak = 0
            return ReversalDecision(self.state, score, "SWING_NOT_MATURE", 0.0)

        if x.survival_s < self.cfg.min_survival_s_forming:
            self.state = ReversalState.FORMING
            self._confirm_streak = 0
            return ReversalDecision(self.state, score, "WAIT_CAUSAL_SURVIVAL", 0.0)

        if x.survival_s >= self.cfg.min_survival_s_early and score >= self.cfg.early_score:
            self._confirm_streak += 1
            self.state = ReversalState.EARLY_CONFIRM
        else:
            self._confirm_streak = 0
            self.state = ReversalState.FORMING

        if self._confirm_streak >= self.cfg.persistence_updates and score >= self.cfg.confirm_score:
            self.state = ReversalState.CONFIRMED

        if self._confirm_streak >= self.cfg.persistence_updates + 1 and score >= self.cfg.hard_score:
            self.state = ReversalState.HARD_CONFIRMED

        fraction = {
            ReversalState.WATCH: 0.0,
            ReversalState.FORMING: 0.0,
            ReversalState.EARLY_CONFIRM: 0.20,
            ReversalState.CONFIRMED: 0.60,
            ReversalState.HARD_CONFIRMED: 1.00,
        }[self.state]

        return ReversalDecision(
            state=self.state,
            score=score,
            reason="CAUSAL_REVERSAL_EVIDENCE",
            paper_fraction_of_intended_position=fraction,
        )
