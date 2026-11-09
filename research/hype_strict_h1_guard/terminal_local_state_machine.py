"""Causal terminal-local tracker for strict H1 L6/K2 research.

Important: a K2-confirmed pivot is provisional. Offline strict labels collapse
consecutive same-side pivots, so a pivot becomes TERMINAL_FINAL only when an
opposite K2 pivot is later confirmed. Research-only; does not place orders.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass(frozen=True)
class K2Pivot:
    side: str
    price: float
    extreme_ts_ms: int
    confirmed_ts_ms: int
    source_id: str = ""

    def __post_init__(self) -> None:
        if self.side not in {"LOW", "HIGH"}:
            raise ValueError("side must be LOW/HIGH")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.confirmed_ts_ms < self.extreme_ts_ms:
            raise ValueError("confirmation precedes extreme")

def more_extreme(new: K2Pivot, old: K2Pivot) -> bool:
    if new.side != old.side:
        raise ValueError("side mismatch")
    return new.price < old.price if new.side == "LOW" else new.price > old.price

class TerminalLocalTracker:
    """Collapse the causal stream of K2 pivots into terminal alternating locals."""

    def __init__(self) -> None:
        self.pending: Optional[K2Pivot] = None
        self.finalized: list[K2Pivot] = []

    def ingest(self, pivot: K2Pivot) -> dict:
        if self.pending is None:
            self.pending = pivot
            return {
                "event": "PIVOT_PROVISIONAL",
                "pending": asdict(pivot),
                "terminal_final": None,
            }

        current = self.pending
        if pivot.side == current.side:
            if more_extreme(pivot, current):
                self.pending = pivot
                return {
                    "event": "PIVOT_REPLACED",
                    "replaced": asdict(current),
                    "pending": asdict(pivot),
                    "terminal_final": None,
                }
            return {
                "event": "SAME_SIDE_WEAKER_IGNORED",
                "pending": asdict(current),
                "terminal_final": None,
            }

        self.finalized.append(current)
        self.pending = pivot
        return {
            "event": "TERMINAL_FINAL_AND_FLIP",
            "terminal_final": asdict(current),
            "pending": asdict(pivot),
            "finalized_at_ms": pivot.confirmed_ts_ms,
        }

    def snapshot(self) -> dict:
        return {
            "pending": asdict(self.pending) if self.pending else None,
            "finalized": [asdict(x) for x in self.finalized],
        }

def contract() -> dict:
    return {
        "name": "HYPE_STRICT_H1_TERMINAL_LOCAL_TRACKER_V1",
        "role": "STRUCTURAL_CERTIFICATION",
        "k2_pivot_is_terminal_final": False,
        "same_side_rule": "replace only with a more-extreme K2 pivot",
        "terminal_rule": "pending pivot becomes TERMINAL_FINAL only when an opposite K2 pivot is confirmed",
        "early_prediction_authorizes_terminal_final": False,
        "real_orders": False,
    }
