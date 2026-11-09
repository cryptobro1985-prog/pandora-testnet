from __future__ import annotations

import math
from typing import Any

from research.hype_false_local_entry.time_to_confirmation_engine import ConfirmationEvidence
from research.hype_local_only.live_features import live_to_archive_features


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _window(checkpoint_s: int) -> int:
    for w in (300, 180, 60, 30, 15, 5):
        if checkpoint_s >= w:
            return w
    return 5


def _same_side_liquidation_exhaustion(side: str, ts_ms: int, state, checkpoint_s: int) -> float:
    """Return [-1,1]: +1 exhausted, 0 unchanged/unknown, -1 accelerating.

    The raw stream uses positive side for long-liquidation events and negative
    side for short-liquidation events, matching feature_discovery.py.
    """
    rows = list(getattr(state, "liqs", []) or [])
    if not rows:
        return 0.0
    side = side.upper()
    want_positive = side == "LOW"
    baseline_s = max(60, min(300, int(checkpoint_s)))
    recent_s = max(15, min(60, baseline_s // 3))
    base = []
    recent = []
    for z in rows:
        zts = int(z.get("ts_ms", 0) or 0)
        if zts < ts_ms - baseline_s * 1000:
            continue
        sign = float(z.get("side", 0) or 0)
        same = sign > 0 if want_positive else sign < 0
        if not same:
            continue
        notion = max(0.0, float(z.get("notional", 0.0) or 0.0))
        base.append(notion)
        if zts >= ts_ms - recent_s * 1000:
            recent.append(notion)
    base_notional = sum(base)
    if base_notional <= 0:
        return 0.0
    baseline_rate = base_notional / baseline_s
    recent_rate = sum(recent) / recent_s
    ratio = recent_rate / max(baseline_rate, 1e-12)
    return _clip(1.0 - ratio)


def _book_recovery_score(fx: dict[str, float], checkpoint_s: int) -> float:
    values = []
    v = fx.get("discovery__book_depth_imbalance_10_rev")
    if _finite(v):
        values.append(_clip(v))
    book_w = 15 if checkpoint_s < 60 else 60 if checkpoint_s < 180 else 180
    for key in (
        f"discovery__book_add_imbalance_{book_w}s_rev",
        f"discovery__book_cancel_pressure_{book_w}s_rev",
    ):
        v = fx.get(key)
        if _finite(v):
            values.append(_clip(v))
    return sum(values) / len(values) if values else 0.0


def _book_quality_ok(state) -> bool:
    bids = getattr(state, "book_bids", {}) or {}
    asks = getattr(state, "book_asks", {}) or {}
    if not bids or not asks:
        return True
    try:
        return max(float(p) for p in bids) < min(float(p) for p in asks)
    except Exception:
        return False


def build_confirmation_evidence(
    *,
    side: str,
    candidate,
    checkpoint_s: int,
    ts_ms: int,
    price: float,
    x: dict[str, Any],
    state,
) -> tuple[ConfirmationEvidence, dict[str, float]]:
    """Build an on-time TTC snapshot from existing causal live state.

    This adapter never reads teacher labels, K2 terminality, TARGET_IDS or
    future candles. It is a shadow research adapter only.
    """
    age_s = max(0.0, (int(ts_ms) - int(candidate.extreme_ts_ms)) / 1000.0)
    fx = live_to_archive_features(
        side,
        age_s,
        float(candidate.extreme_price),
        float(price),
        x,
        state,
    )
    w = _window(int(checkpoint_s))
    reversal_bps = float(fx.get("retrace_bps", 0.0) or 0.0)
    # live_to_archive_features scales efficiency by 1e6; restore raw scale
    # used in the causal-signature research handoff.
    rev_eff = float(fx.get(f"rev_eff_{w}s", 0.0) or 0.0) / 1e6
    old_eff = float(fx.get(f"old_eff_{w}s", 0.0) or 0.0) / 1e6
    liq_exhaustion = _same_side_liquidation_exhaustion(
        side, int(ts_ms), state, int(checkpoint_s)
    )
    book_recovery = _book_recovery_score(fx, int(checkpoint_s))

    # OI response is retained as diagnostic context but neutral in v1 scoring
    # until the sign/state relation is frozen out-of-sample.
    oi_delta = x.get(f"oi_delta_{w}s", x.get("oi_delta_300s"))
    oi_price_agreement = 0.0

    ev = ConfirmationEvidence(
        ts_ms=int(ts_ms),
        side=str(side),
        extreme_ts_ms=int(candidate.extreme_ts_ms),
        extreme_price=float(candidate.extreme_price),
        price=float(price),
        reversal_return_bps=reversal_bps,
        flow_efficiency=rev_eff,
        opposing_impact_efficiency=old_eff,
        same_side_liq_decay=liq_exhaustion,
        book_recovery=book_recovery,
        oi_price_agreement=oi_price_agreement,
        no_new_extreme=True,
        data_quality_ok=_book_quality_ok(state),
    )
    diagnostics = {
        "age_s": age_s,
        "window_s": float(w),
        "reversal_return_bps": reversal_bps,
        "flow_efficiency": rev_eff,
        "opposing_impact_efficiency": old_eff,
        "liquidation_exhaustion": liq_exhaustion,
        "book_recovery": book_recovery,
        "oi_delta": float(oi_delta) if _finite(oi_delta) else 0.0,
        "book_quality_ok": 1.0 if ev.data_quality_ok else 0.0,
    }
    return ev, diagnostics
