"""HIGH Flow V3 regime gate for HYPE.

Research/PAPER only. The frozen HARD120 primary is unchanged. This gate is
applied only to the HIGH Flow V2 expansion at the exact +120m checkpoint.

Four-regime development found two distinct failure modes in V2:
1) low continuation participation after the first seller burst;
2) an overextended reversal excursion that later rebounds before +120m.

V3 therefore requires:
- at least 2,600 executed trades in completed minutes +15..+30 after the HIGH;
- maximum causal reversal excursion through +120m <= 220 bps.

These thresholds were selected AFTER inspecting Jul/Aug, late-Aug, September,
and Oct/Nov 2026. They are development fit, NOT untouched OOS proof.
Promotion is FORWARD_SCORE_ONLY. Real orders remain disabled.
"""
from __future__ import annotations
from typing import Iterable, Mapping

MIN_CONTINUATION_TRADES_15_30 = 2600
MAX_REVERSAL_EXCURSION_120_BPS = 220.0


def metrics(*, side: str, candidate_bar_start_ms: int, extreme_price: float,
            sample_ts_ms: int, completed_m1_rows: Iterable[Mapping]) -> dict:
    if str(side).upper() != "HIGH":
        return {"ready": False, "reason": "high_only"}

    rows = sorted(
        (
            r for r in completed_m1_rows
            if int(r.get("bar_end_ms") or r.get("ts_ms") or 0) <= int(sample_ts_ms)
        ),
        key=lambda r: int(r.get("start_ms") or 0),
    )
    idx = next(
        (i for i, r in enumerate(rows)
         if int(r.get("start_ms") or 0) == int(candidate_bar_start_ms)),
        None,
    )
    if idx is None:
        return {"ready": False, "reason": "candidate_bar_missing"}

    path = rows[idx + 1:]
    if len(path) < 30:
        return {"ready": False, "reason": "insufficient_post_candidate_m1",
                "post_candidate_bars": len(path)}

    continuation = path[15:30]
    continuation_trades = sum(int(r.get("trade_count") or 0) for r in continuation)

    p = float(extreme_price)
    if p <= 0:
        return {"ready": False, "reason": "invalid_extreme_price"}
    lows = [float(r["low"]) for r in path if float(r.get("low") or 0) > 0]
    if not lows:
        return {"ready": False, "reason": "no_valid_lows"}
    max_reversal_bps = max(0.0, (p / min(lows) - 1.0) * 10_000.0)

    checks = {
        "continuation_participation": continuation_trades >= MIN_CONTINUATION_TRADES_15_30,
        "reversal_not_overextended": max_reversal_bps <= MAX_REVERSAL_EXCURSION_120_BPS,
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "continuation_trades_15_30": continuation_trades,
        "min_continuation_trades_15_30": MIN_CONTINUATION_TRADES_15_30,
        "max_reversal_excursion_120_bps": max_reversal_bps,
        "max_allowed_reversal_excursion_120_bps": MAX_REVERSAL_EXCURSION_120_BPS,
        "post_candidate_bars": len(path),
    }


def contract() -> dict:
    return {
        "name": "HARD120_HIGH_FLOW_REGIME_GATE_V3",
        "role": "HIGH_FLOW_V2_REGIME_VETO_SHADOW_ONLY",
        "side": "HIGH",
        "min_continuation_trades_15_30": MIN_CONTINUATION_TRADES_15_30,
        "max_reversal_excursion_120_bps": MAX_REVERSAL_EXCURSION_120_BPS,
        "primary_contract_unchanged": True,
        "low_logic_changed": False,
        "core_flip_authorized": False,
        "selection_periods": [
            "2026-07-12..2026-08-07",
            "2026-08-08..2026-09-01",
            "2026-09-01..2026-10-01",
            "2026-10-04..2026-11-03",
        ],
        "historical_status": "FOUR_REGIME_DEVELOPMENT_FIT_NOT_OOS",
        "promotion": "FORWARD_SCORE_ONLY",
    }
