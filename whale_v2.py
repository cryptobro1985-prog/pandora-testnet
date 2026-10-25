"""Whale Liquidation 2.0 PAPER experiment.

Pure strategy logic only. Runtime persistence/accounting lives in app.py.

Design goals:
- keep Whale Liquidation v1 unchanged for an A/B week;
- v2 only enters when liquidation distance is actively contracting;
- require aligned trend + book/flow/CVD + participation;
- invalidate a pre-liquidation thesis when distance persistently widens;
- after the liquidation level is touched, track the best post-liquidation
  extreme without requiring that extreme to stay inside a tiny recent window.

This module never places real orders.
"""
import copy
import math

WL2_POLICY = "whale_liquidation_v2_frozen_week1"
WL2_MARGIN_FRACTION = 0.20
WL2_LEVERAGE = 25.0
WL2_MAX_POSITIONS = 5
WL2_MIN_SCORE = 82.0
WL2_MIN_RANK = 80.0
WL2_MAX_ENTRY_DISTANCE_PCT = 0.90
WL2_DISTANCE_POINTS = 4
WL2_MIN_CONTRACTION_PCT = 0.05
WL2_MIN_CONFIRMATIONS = 4
WL2_MIN_FLOW = 0.12
WL2_MIN_BOOK_IMBALANCE = 0.10
WL2_MAX_SPREAD_BPS = 12.0
WL2_MIN_POST_LIQ_GIVEBACK = 0.0004
WL2_MAX_POST_LIQ_GIVEBACK = 0.0020


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _remaining_pct(victim_side, mark, liquidation_price):
    mark = _finite(mark)
    liq = _finite(liquidation_price)
    if mark <= 0 or liq <= 0:
        return None
    if victim_side == "long":
        return ((mark / liq) - 1.0) * 100.0
    if victim_side == "short":
        return ((liq / mark) - 1.0) * 100.0
    return None


def _target_reached(victim_side, mark, liquidation_price):
    mark = _finite(mark)
    liq = _finite(liquidation_price)
    if mark <= 0 or liq <= 0:
        return False
    return (victim_side == "long" and mark <= liq) or (victim_side == "short" and mark >= liq)


class EligibilityTracker:
    """Tracks distance contraction across scanner passes."""

    def __init__(self):
        self._distance = {}
        self._seen_scan = {}

    def observe(self, candidates, scan_id):
        qualified = []
        rejected = {}
        observed = []
        seen = set()

        for raw in candidates:
            x = copy.deepcopy(raw)
            symbol = str(x.get("symbol") or "")
            side = int(x.get("side") or 0)
            cluster = str(x.get("cluster_id") or symbol)
            key = (cluster, symbol, side)
            seen.add(key)

            distance = _finite(x.get("distance_pct"), 99.0)
            hist = self._distance.setdefault(key, [])
            hist.append(distance)
            if len(hist) > 8:
                del hist[:-8]
            self._seen_scan[key] = scan_id

            reasons = []
            score = _finite(x.get("score"))
            rank = _finite(x.get("whale_rank_score"), score)
            dynamic = max(0.01, _finite(x.get("dynamic_entry_distance_pct"), WL2_MAX_ENTRY_DISTANCE_PCT))
            entry_cap = min(WL2_MAX_ENTRY_DISTANCE_PCT, dynamic)

            if score < WL2_MIN_SCORE:
                reasons.append("score_below_v2_min")
            if rank < WL2_MIN_RANK:
                reasons.append("rank_below_v2_min")
            if distance > entry_cap:
                reasons.append("not_close_enough")

            contraction_window = hist[-WL2_DISTANCE_POINTS:]
            contraction_steps = 0
            contraction = 0.0
            if len(contraction_window) >= 3:
                contraction_steps = sum(
                    contraction_window[i] < contraction_window[i - 1] - 1e-9
                    for i in range(1, len(contraction_window))
                )
                contraction = contraction_window[0] - contraction_window[-1]
            required_steps = max(2, len(contraction_window) - 2)
            contracting = (
                len(contraction_window) >= 3
                and contraction_steps >= required_steps
                and contraction >= WL2_MIN_CONTRACTION_PCT
            )
            if not contracting:
                reasons.append("distance_not_contracting")

            r15 = _finite(x.get("r15"))
            r60 = _finite(x.get("r60"))
            r300_raw = x.get("r300")
            r900_raw = x.get("r900")
            r300 = None if r300_raw is None else _finite(r300_raw)
            r900 = None if r900_raw is None else _finite(r900_raw)

            trend_votes = [
                side * r15 >= 0.00035,
                side * r60 >= 0.00070,
            ]
            if r300 is not None:
                trend_votes.append(side * r300 >= 0.0010)
            if r900 is not None:
                trend_votes.append(side * r900 >= 0.0015)
            longer_opposed = (
                (r300 is not None and side * r300 <= -0.0010)
                or (r900 is not None and side * r900 <= -0.0015)
            )
            trend_aligned = sum(bool(v) for v in trend_votes) >= 2 and not longer_opposed
            if not trend_aligned:
                reasons.append("trend_not_aligned")

            flow = _finite(x.get("flow_imbalance"))
            cvd = _finite(x.get("cvd_1m"))
            imbalance = _finite(x.get("orderbook_imbalance"))
            spread = _finite(x.get("spread_bps"), 9999.0)
            confirmations = int(_finite(x.get("micro_confirmations")))
            flow_ok = side * flow >= WL2_MIN_FLOW
            cvd_ok = side * cvd > 0
            book_ok = side * imbalance >= WL2_MIN_BOOK_IMBALANCE and spread <= WL2_MAX_SPREAD_BPS
            confirm_ok = confirmations >= WL2_MIN_CONFIRMATIONS
            if not flow_ok:
                reasons.append("flow_not_confirmed")
            if not cvd_ok:
                reasons.append("cvd_not_confirmed")
            if not book_ok:
                reasons.append("book_not_confirmed")
            if not confirm_ok:
                reasons.append("micro_confirmations_below_v2_min")

            burst = _finite(x.get("volume_burst_ratio"))
            vol_z = x.get("volume_rate_z")
            participation_ok = burst >= 2.0 or (vol_z is not None and _finite(vol_z) >= 2.5)
            if not participation_ok:
                reasons.append("participation_not_abnormal")

            x["wl2_policy"] = WL2_POLICY
            x["wl2_entry_distance_cap_pct"] = round(entry_cap, 6)
            x["wl2_distance_history_pct"] = [round(v, 6) for v in contraction_window]
            x["wl2_distance_contraction_pct"] = round(contraction, 6)
            x["wl2_distance_contraction_steps"] = int(contraction_steps)
            x["wl2_trend_aligned"] = bool(trend_aligned)
            x["wl2_flow_ok"] = bool(flow_ok)
            x["wl2_cvd_ok"] = bool(cvd_ok)
            x["wl2_book_ok"] = bool(book_ok)
            x["wl2_participation_ok"] = bool(participation_ok)
            x["wl2_reject_reasons"] = reasons
            observed.append(copy.deepcopy(x))

            if reasons:
                for reason in reasons:
                    rejected[reason] = rejected.get(reason, 0) + 1
                continue
            qualified.append(x)

        # Bounded cleanup: a candidate absent for 20 scanner passes loses its
        # contraction history and must rebuild evidence if it reappears.
        for key, last in list(self._seen_scan.items()):
            if scan_id - last > 20:
                self._seen_scan.pop(key, None)
                self._distance.pop(key, None)

        qualified.sort(
            key=lambda x: (
                _finite(x.get("whale_rank_score"), _finite(x.get("score"))),
                -_finite(x.get("distance_pct"), 99.0),
                _finite(x.get("liquidation_flow_to_depth")),
            ),
            reverse=True,
        )
        return qualified, rejected, observed


def initial_position_state(candidate, entry_price, opened_at):
    """Return the v2-only feature/state payload persisted with a new position."""
    x = copy.deepcopy(candidate)
    entry_distance = _finite(x.get("distance_pct"), 99.0)
    dynamic = _finite(x.get("dynamic_entry_distance_pct"), WL2_MAX_ENTRY_DISTANCE_PCT)
    invalidation = min(
        1.25,
        max(
            0.45,
            entry_distance * 1.75,
            entry_distance + 0.35,
        ),
    )
    x.update(
        {
            "engine": "whale_liquidation_v2",
            "wl2_policy": WL2_POLICY,
            "wl2_opened_at": opened_at,
            "wl2_entry_price": float(entry_price),
            "wl2_entry_distance_pct": entry_distance,
            "wl2_invalidation_distance_pct": round(invalidation, 6),
            "wl2_distance_history_after_entry": [entry_distance],
            "wl2_widen_streak": 0,
            "wl2_thesis_break_streak": 0,
            "wl2_liquidation_level_reached_at": None,
            "wl2_post_liq_history": [],
            "wl2_post_liq_best_price": None,
            "wl2_mfe_price_move": 0.0,
            "wl2_mae_price_move": 0.0,
        }
    )
    return x


def evaluate_position(position, mark, evaluated_at, flow=0.0, r15=None, r60=None):
    """Evaluate one WL2 PAPER position.

    Returns (updated_position, close_reason). The close reasons are deliberately
    explicit so the A/B audit can distinguish thesis invalidation from
    post-liquidation local-extreme harvesting.
    """
    pos = copy.deepcopy(position)
    mark = _finite(mark)
    if mark <= 0:
        raise ValueError("invalid mark")

    entry = _finite(pos.get("entry"))
    side = int(pos.get("side") or 0)
    if entry <= 0 or side not in (-1, 1):
        raise ValueError("invalid position")

    features = copy.deepcopy(pos.get("features") or {})
    liq = _finite(features.get("liquidation_price"))
    victim = str(features.get("victim_side") or "").lower()
    if liq <= 0 or victim not in ("long", "short"):
        raise ValueError("missing liquidation target")

    price_move = side * (mark / entry - 1.0)
    features["wl2_mfe_price_move"] = max(
        _finite(features.get("wl2_mfe_price_move")),
        price_move,
    )
    features["wl2_mae_price_move"] = min(
        _finite(features.get("wl2_mae_price_move")),
        price_move,
    )

    reached = _target_reached(victim, mark, liq)
    reached_at = features.get("wl2_liquidation_level_reached_at")

    if not reached_at and reached:
        features["wl2_liquidation_level_reached_at"] = evaluated_at
        features["wl2_liquidation_level_reached_mark"] = mark
        features["wl2_post_liq_history"] = [mark]
        features["wl2_post_liq_best_price"] = mark
        features["wl2_widen_streak"] = 0
        features["wl2_thesis_break_streak"] = 0
        pos["features"] = features
        pos["last_price"] = mark
        return pos, None

    if not features.get("wl2_liquidation_level_reached_at"):
        remaining = _remaining_pct(victim, mark, liq)
        history = [
            _finite(v) for v in features.get("wl2_distance_history_after_entry", [])
            if _finite(v, -1.0) >= 0
        ][-19:]
        if remaining is not None:
            history.append(max(0.0, remaining))
        features["wl2_distance_history_after_entry"] = history[-20:]

        widening = len(history) >= 2 and history[-1] > history[-2] + 0.015
        features["wl2_widen_streak"] = (
            int(features.get("wl2_widen_streak", 0)) + 1 if widening else 0
        )

        r15v = 0.0 if r15 is None else _finite(r15)
        r60v = 0.0 if r60 is None else _finite(r60)
        flow_against = side * _finite(flow) <= -0.08
        trend_against = (
            r15 is not None
            and r60 is not None
            and side * r15v <= -0.00035
            and side * r60v <= -0.00070
        )
        thesis_break = flow_against and trend_against
        features["wl2_thesis_break_streak"] = (
            int(features.get("wl2_thesis_break_streak", 0)) + 1
            if thesis_break
            else 0
        )
        features["wl2_remaining_to_liquidation_pct"] = remaining
        features["wl2_flow_against"] = bool(flow_against)
        features["wl2_trend_against"] = bool(trend_against)

        invalidation = _finite(features.get("wl2_invalidation_distance_pct"), 0.75)
        if (
            remaining is not None
            and remaining > invalidation
            and int(features.get("wl2_widen_streak", 0)) >= 3
        ):
            pos["features"] = features
            pos["last_price"] = mark
            return pos, "wl2_pre_liq_distance_invalidation"

        if int(features.get("wl2_thesis_break_streak", 0)) >= 3:
            pos["features"] = features
            pos["last_price"] = mark
            return pos, "wl2_pre_liq_thesis_break"

        pos["features"] = features
        pos["last_price"] = mark
        return pos, None

    # Post-liquidation: preserve the all-time best post-trigger extreme. The
    # v1 "peak must be recent" requirement is intentionally absent.
    history = [
        _finite(v) for v in features.get("wl2_post_liq_history", [])
        if _finite(v, -1.0) > 0
    ][-119:]
    history.append(mark)
    history = history[-120:]

    best = features.get("wl2_post_liq_best_price")
    best = mark if best is None else _finite(best, mark)
    if side > 0:
        best = max(best, mark)
        giveback = max(0.0, (best - mark) / best)
        favorable = max(0.0, best / liq - 1.0)
    else:
        best = min(best, mark)
        giveback = max(0.0, (mark - best) / best)
        favorable = max(0.0, 1.0 - best / liq)

    adverse_steps = 0
    slope_flip = False
    if len(history) >= 4:
        steps = [history[i] - history[i - 1] for i in range(1, len(history))]
        if side > 0:
            adverse_steps = sum(v < 0 for v in steps[-3:])
            slope_flip = history[-1] < history[-3] and history[-2] <= history[-3]
        else:
            adverse_steps = sum(v > 0 for v in steps[-3:])
            slope_flip = history[-1] > history[-3] and history[-2] >= history[-3]

    weakening = adverse_steps >= 2 and slope_flip
    allowed = max(
        WL2_MIN_POST_LIQ_GIVEBACK,
        min(WL2_MAX_POST_LIQ_GIVEBACK, favorable * 0.20),
    )
    local_exit = len(history) >= 5 and weakening and giveback >= allowed

    features["wl2_post_liq_history"] = history
    features["wl2_post_liq_best_price"] = best
    features["wl2_post_liq_favorable_move"] = favorable
    features["wl2_post_liq_giveback"] = giveback
    features["wl2_post_liq_allowed_giveback"] = allowed
    features["wl2_post_liq_adverse_steps"] = adverse_steps
    features["wl2_post_liq_slope_flip"] = bool(slope_flip)
    features["wl2_post_liq_weakening"] = bool(weakening)

    pos["features"] = features
    pos["last_price"] = mark
    return pos, "wl2_post_liq_local_extreme_weakening" if local_exit else None


def learning_summary(trades):
    """Small deterministic summary used for daily observe-only learning."""
    rows = list(trades)
    n = len(rows)
    if not n:
        return {
            "samples": 0,
            "wins": 0,
            "win_rate": None,
            "avg_pnl": None,
            "total_pnl": 0.0,
            "profit_factor": None,
            "policy": WL2_POLICY,
            "adaptation_mode": "observe_only_frozen_week1",
        }
    pnls = [_finite(r.get("pnl")) for r in rows]
    wins = sum(v > 0 for v in pnls)
    gross_win = sum(v for v in pnls if v > 0)
    gross_loss = -sum(v for v in pnls if v < 0)
    return {
        "samples": n,
        "wins": wins,
        "win_rate": wins / n,
        "avg_pnl": sum(pnls) / n,
        "total_pnl": sum(pnls),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "policy": WL2_POLICY,
        "adaptation_mode": "observe_only_frozen_week1",
    }
