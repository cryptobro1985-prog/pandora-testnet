from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ReversalState(str, Enum):
    WATCH = "WATCH"
    FORMING = "FORMING"
    EARLY_PROBE = "EARLY_PROBE"
    CONFIRMED = "CONFIRMED"
    HARD_CONFIRMED = "HARD_CONFIRMED"
    ULTRA_CONFIRMED = "ULTRA_CONFIRMED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class Evidence:
    side: str
    survival_s: int
    swing_atr_mult: float
    retrace_fraction: float
    edge_recovery_60m: float
    edge_recovery_6h: float
    rev_return_180s: float = 0.0
    rev_return_300s: float = 0.0
    rev_flow_180s: float = 0.0
    rev_flow_3m: float = 0.0
    rev_eff_300s: float = 0.0
    macd_hist_rev_bps: float = 0.0
    macd_slope3_rev_bps: float = 0.0
    same_side_extreme_broken: bool = False
    oi_delta_rev: Optional[float] = None


@dataclass(frozen=True)
class Decision:
    state: ReversalState
    target_paper_fraction: float
    invalidate_stop_at_extreme: bool
    reason: str


class FalseLocalEntryEngine:
    """Causal H1 reversal detector for research/paper replay.

    Ordinary intrawave corrections must not cause an immediate full reversal.
    Evidence is accumulated in stages. A new same-side extreme invalidates the
    candidate immediately.

    Fractions are fractions of an intended paper position, not real-money
    recommendations. Real order placement is deliberately absent.
    """

    def evaluate(self, x: Evidence) -> Decision:
        if x.same_side_extreme_broken:
            return Decision(
                ReversalState.INVALIDATED,
                0.0,
                True,
                "new same-side extreme invalidated the candidate",
            )

        if x.swing_atr_mult < 2.0 or x.survival_s < 600:
            return Decision(ReversalState.FORMING, 0.0, True, "not mature enough")

        early_votes = sum(
            [
                x.retrace_fraction >= 0.08,
                x.edge_recovery_60m >= 0.20,
                x.edge_recovery_6h >= 0.08,
                x.rev_return_300s >= 0.0,
                x.macd_hist_rev_bps >= 0.0,
                x.rev_flow_180s >= 0.0,
            ]
        )
        if x.survival_s >= 600 and early_votes >= 4:
            best = Decision(
                ReversalState.EARLY_PROBE,
                0.10,
                True,
                "10m causal reversal probe",
            )
        else:
            best = Decision(ReversalState.FORMING, 0.0, True, "insufficient early evidence")

        if (
            x.survival_s >= 1800
            and x.swing_atr_mult >= 3.0
            and x.retrace_fraction >= 0.12
            and x.edge_recovery_60m >= 0.30
            and x.edge_recovery_6h >= 0.20
            and x.macd_hist_rev_bps >= -1.0
            and x.rev_flow_3m >= -0.10
        ):
            best = Decision(
                ReversalState.CONFIRMED,
                0.35,
                True,
                "30m structural confirmation",
            )

        if (
            x.survival_s >= 3600
            and x.swing_atr_mult >= 3.5
            and x.retrace_fraction >= 0.15
            and x.edge_recovery_60m >= 0.20
            and x.edge_recovery_6h >= 0.12
            and x.macd_hist_rev_bps >= -3.0
            and x.rev_flow_3m >= 0.10
        ):
            best = Decision(
                ReversalState.HARD_CONFIRMED,
                0.70,
                True,
                "60m high-confidence structural reversal",
            )

        if (
            x.survival_s >= 3600
            and x.swing_atr_mult >= 4.5
            and x.retrace_fraction >= 0.15
            and x.edge_recovery_60m >= 0.45
            and x.edge_recovery_6h >= 0.10
            and x.macd_hist_rev_bps >= -1.0
            and x.rev_flow_3m >= 0.15
        ):
            best = Decision(
                ReversalState.ULTRA_CONFIRMED,
                1.00,
                True,
                "60m ultra gate; in-sample research only",
            )

        return best


class PositionRouter:
    """Paper router that prevents early opposite signals from whipsawing."""

    def desired_fraction(
        self,
        current_side: Optional[str],
        decision: Decision,
        signal_side: str,
    ) -> tuple[Optional[str], float]:
        if decision.state in {
            ReversalState.WATCH,
            ReversalState.FORMING,
            ReversalState.INVALIDATED,
        }:
            return current_side, 0.0 if current_side is None else 1.0

        target_side = "LONG" if signal_side == "LOW" else "SHORT"

        if current_side is None or current_side == target_side:
            return target_side, decision.target_paper_fraction

        if decision.state in {
            ReversalState.EARLY_PROBE,
            ReversalState.CONFIRMED,
        }:
            return current_side, 1.0

        return target_side, decision.target_paper_fraction
