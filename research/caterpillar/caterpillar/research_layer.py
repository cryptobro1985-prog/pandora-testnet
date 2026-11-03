"""Research-only hypothesis layer for Caterpillar.

This module never sends orders. It deliberately evaluates multiple causal H1-local,
entry, exit and re-entry hypotheses in parallel so the research pipeline does not
mistake one hard-coded rule for market truth.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class LocalVariant:
    name: str
    lookback: int
    retreat_bps: float
    confirm_bars: int


LOCAL_VARIANTS = (
    LocalVariant("h1_lb2_retreat0_b1", 2, 0.0, 1),
    LocalVariant("h1_lb4_retreat0_b1", 4, 0.0, 1),
    LocalVariant("h1_lb6_retreat5_b1", 6, 5.0, 1),
    LocalVariant("h1_lb6_retreat10_b1", 6, 10.0, 1),
    LocalVariant("h1_lb10_retreat5_b2", 10, 5.0, 2),
)
LOCAL_OUTCOME_HOURS = (1, 2, 4)


def local_flow_evidence(kind, flow):
    """Causal flow evidence available at H1-local confirmation time.

    Tags are research labels, not gates. They let history answer whether a
    structural H1 retreat is materially improved by exhaustion/absorption/
    efficient opposite response for a particular token.
    """
    if not flow:
        return []
    low = kind == "LOW"
    dominant_side = -1 if low else 1
    reversal_side = 1 if low else -1
    tags = []
    imbalance = float(flow.get("imbalance", 0.0) or 0.0)
    move = float(flow.get("move_bps", 0.0) or 0.0)
    price_scale = float(flow.get("price_scale_bps", 0.0) or 0.0)
    if low and flow.get("sell_absorption"):
        tags.append("SELL_ABSORPTION_AT_LOW")
    if not low and flow.get("buy_absorption"):
        tags.append("BUY_ABSORPTION_AT_HIGH")
    decel = flow.get("sell_deceleration") if low else flow.get("buy_deceleration")
    if decel is not None and decel > 0:
        tags.append("DOMINANT_FLOW_DECELERATION")
    if imbalance * reversal_side > 0 and move * reversal_side > 0:
        tags.append("OPPOSITE_FLOW_PRICE_RESPONSE")
    if imbalance * dominant_side > 0 and move * dominant_side <= 0:
        tags.append("DOMINANT_FLOW_FAILED_TO_MOVE_PRICE")
    if price_scale > 0 and move * reversal_side >= price_scale:
        tags.append("STRONG_REVERSAL_PRICE_RESPONSE")
    if flow.get("large_trade_count", 0):
        tags.append("LARGE_TRADE_CONTEXT")
    if flow.get("notional_z", 0) is not None and flow.get("notional_z", 0) >= 2:
        tags.append("VOLUME_BURST_CONTEXT")
    return tags


@dataclass
class ResearchLocal:
    ident: str
    variant: str
    kind: str
    price: float
    formed_bar_start: float
    last_extreme_bar_start: float
    status: str = "FORMING"
    retreat_count: int = 0
    confirmed_ts: float | None = None
    signal_price: float | None = None


class MultiLocalResearch:
    """Causal multi-hypothesis H1 local tracker.

    A variant may form/update/confirm a local only from CLOSED H1 bars already
    available at that timestamp. Outcomes are measured only AFTER confirmation.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bars = deque(maxlen=256)
        self.pending: dict[str, ResearchLocal] = {}
        self.outcomes: list[dict] = []
        self.seq = 0
        self.discontinuity = False

    @staticmethod
    def _bar_dict(bar):
        return {
            "start": float(bar.start), "end": float(bar.end),
            "available_ts": float(bar.available_ts),
            "open": float(bar.open), "high": float(bar.high),
            "low": float(bar.low), "close": float(bar.close),
            "volume": float(bar.volume),
        }

    def _emit(self, emit, ts, stage, local, **extra):
        emit("local_hypotheses", ts=ts, stage=stage,
             hypothesis=local.variant, local=asdict(local), **extra)

    def gap(self, ts, emit, reason="DATA_GAP"):
        for local in list(self.pending.values()):
            local.status = "INVALIDATED"
            self._emit(emit, ts, "INVALIDATED", local, reason=reason)
        self.pending.clear()
        self.discontinuity = True

    def _advance_outcomes(self, bar, observed_at, emit, profile):
        remaining = []
        for row in self.outcomes:
            side = 1 if row["kind"] == "LOW" else -1
            entry = row["signal_price"]
            fav = ((bar.high / entry - 1) * 10000 if side == 1
                   else (entry / bar.low - 1) * 10000)
            adv = ((bar.low / entry - 1) * 10000 if side == 1
                   else (entry / bar.high - 1) * 10000)
            close_move = (bar.close / entry - 1) * 10000 * side
            row["mfe_bps"] = max(row["mfe_bps"], fav)
            row["mae_bps"] = min(row["mae_bps"], adv)
            row["bars_seen"] += 1
            row["last_close_net_bps"] = close_move
            if row["bars_seen"] >= row["horizon_hours"]:
                payload = {**row, "status": "COMPLETE", "completed_ts": observed_at}
                emit("local_hypotheses", ts=observed_at, stage="OUTCOME", **payload)
                label = f'{row["variant"]}_{row["horizon_hours"]}h'
                base_key = f'{row["phase"]}/local/{row["kind"]}/{label}'
                profile.outcome(base_key, close_move, ts=row["confirmed_ts"])
                metric_base = f'local_pattern/{row["kind"]}/{label}/'
                profile.add(metric_base+"close_bps", close_move)
                profile.add(metric_base+"mfe_bps", row["mfe_bps"])
                profile.add(metric_base+"mae_bps", row["mae_bps"])
                profile.add(metric_base+"mfe_capture_ratio", close_move/row["mfe_bps"] if row["mfe_bps"] > 0 else None)
                for tag in row.get("flow_evidence", []):
                    tagged = label+"+"+tag
                    profile.outcome(f'{row["phase"]}/local/{row["kind"]}/{tagged}', close_move, ts=row["confirmed_ts"])
                    tagged_base = f'local_pattern/{row["kind"]}/{tagged}/'
                    profile.add(tagged_base+"close_bps", close_move)
                    profile.add(tagged_base+"mfe_bps", row["mfe_bps"])
                    profile.add(tagged_base+"mae_bps", row["mae_bps"])
                    profile.add(tagged_base+"mfe_capture_ratio", close_move/row["mfe_bps"] if row["mfe_bps"] > 0 else None)
            else:
                remaining.append(row)
        self.outcomes = remaining

    def on_closed_bar(self, bar, observed_at, latest_flow, emit, profile, phase, seeded=False):
        current = self._bar_dict(bar)
        if self.bars and current["start"] != self.bars[-1]["end"]:
            self.gap(observed_at, emit, "MISSING_H1_INTERVAL")
        self._advance_outcomes(bar, observed_at, emit, profile)

        # First process existing candidates. A candidate can only be confirmed
        # by a later CLOSED H1 that retreats from the extreme.
        for variant in LOCAL_VARIANTS:
            for kind in ("LOW", "HIGH"):
                key = variant.name + "/" + kind
                local = self.pending.get(key)
                if local is None:
                    continue
                px = current["low"] if kind == "LOW" else current["high"]
                extends = px < local.price if kind == "LOW" else px > local.price
                if extends:
                    local.price = px
                    local.last_extreme_bar_start = current["start"]
                    local.retreat_count = 0
                    local.status = "UPDATED"
                    self._emit(emit, observed_at, "UPDATED", local,
                               reason="NEW_H1_EXTREME", seeded=seeded,
                               latest_flow=latest_flow)
                    continue
                retreat = ((px / local.price - 1) * 10000 if kind == "LOW"
                           else (local.price / px - 1) * 10000)
                if current["start"] > local.last_extreme_bar_start and retreat > variant.retreat_bps:
                    local.retreat_count += 1
                else:
                    local.retreat_count = 0
                if local.retreat_count >= variant.confirm_bars:
                    local.status = "CONFIRMED"
                    local.confirmed_ts = observed_at
                    local.signal_price = current["close"]
                    evidence_tags = local_flow_evidence(kind, latest_flow)
                    self._emit(emit, observed_at, "CONFIRMED", local,
                               reason="CAUSAL_H1_RETREAT", seeded=seeded,
                               retreat_bps=retreat, latest_flow=latest_flow,
                               flow_evidence=evidence_tags)
                    if not seeded:
                        for horizon in LOCAL_OUTCOME_HOURS:
                            self.outcomes.append({
                                "variant": local.variant, "kind": local.kind,
                                "local_id": local.ident, "local_price": local.price,
                                "confirmed_ts": observed_at,
                                "signal_price": current["close"],
                                "horizon_hours": horizon, "bars_seen": 0,
                                "mfe_bps": 0.0, "mae_bps": 0.0,
                                "last_close_net_bps": 0.0, "phase": phase,
                                "flow_evidence": evidence_tags,
                            })
                    del self.pending[key]

        prior = list(self.bars)
        for variant in LOCAL_VARIANTS:
            if len(prior) < variant.lookback:
                continue
            context = prior[-variant.lookback:]
            for kind in ("LOW", "HIGH"):
                key = variant.name + "/" + kind
                if key in self.pending:
                    continue
                extreme = (current["low"] < min(x["low"] for x in context)
                           if kind == "LOW"
                           else current["high"] > max(x["high"] for x in context))
                if not extreme:
                    continue
                self.seq += 1
                px = current["low"] if kind == "LOW" else current["high"]
                local = ResearchLocal(
                    f"{self.symbol}/{variant.name}/{kind}/{self.seq}",
                    variant.name, kind, px, current["start"], current["start"])
                self.pending[key] = local
                self._emit(emit, observed_at, "FORMING", local,
                           reason="EXCEEDS_PRECEDING_CLOSED_H1",
                           seeded=seeded, lookback_bars=variant.lookback,
                           latest_flow=latest_flow)

        self.bars.append(current)
        self.discontinuity = False

    def state_dict(self):
        return {
            "symbol": self.symbol, "bars": list(self.bars),
            "pending": {k: asdict(v) for k, v in self.pending.items()},
            "outcomes": self.outcomes, "seq": self.seq,
            "discontinuity": self.discontinuity,
        }

    def load_state(self, row):
        self.bars = deque(row.get("bars", []), maxlen=256)
        self.pending = {k: ResearchLocal(**v) for k, v in row.get("pending", {}).items()}
        self.outcomes = list(row.get("outcomes", []))
        self.seq = int(row.get("seq", 0))
        self.discontinuity = bool(row.get("discontinuity", False))


def dual_side_entry_research(engine, state, flow, snapshot, forward_by_side):
    """Evaluate LONG and SHORT independently without changing the execution books."""
    profile = engine.profiles[state.symbol]
    for side in (-1, 1):
        direction = "LONG" if side == 1 else "SHORT"
        anchor = engine._anchor(state, side)
        trend_side = 1 if state.trend == "UPTREND" else -1 if state.trend == "DOWNTREND" else 0
        control = engine._control(flow, side)
        accel = flow["buy_acceleration"] if side == 1 else flow["sell_acceleration"]
        own_absorption = flow["buy_absorption"] if side == 1 else flow["sell_absorption"]
        price_response = flow["move_bps"] * side
        beyond = anchor is not None and (flow["price"] - anchor.price) * side <= 0
        distance_bps = (abs(flow["price"] / anchor.price - 1) * 10000 if anchor else None)
        near_local = anchor is not None and distance_bps <= max(15.0, flow["price_scale_bps"] * 3)
        continuation_context = trend_side == side

        shared = []
        if len(state.history) < engine.config.warmup_blocks:
            shared.append("WARMUP")
        if not control:
            shared.append("NO_PRICE_RESPONSIVE_CONTROL")
        if accel is None or accel <= 0:
            shared.append("NO_ACCELERATION")
        if own_absorption:
            shared.append("OWN_ABSORPTION")
        if price_response <= 0:
            shared.append("NO_DIRECTIONAL_PRICE_RESPONSE")

        hypotheses = [
            ("FROM_LOCAL", anchor is not None and near_local,
             [] if anchor else ["NO_VALID_CONFIRMED_LOCAL"]),
            ("CONTINUATION", continuation_context,
             [] if continuation_context else ["NO_MATCHING_TREND"]),
            ("DIRECTIONAL", True, []),
        ]
        for mode, context_ok, mode_reasons in hypotheses:
            reasons = list(shared) + list(mode_reasons)
            if anchor is not None and beyond:
                reasons.append("BEYOND_LOCAL")
            if mode == "FROM_LOCAL" and not near_local and anchor is not None:
                reasons.append("TOO_FAR_FROM_LOCAL_FOR_LOCAL_HYPOTHESIS")
            accepted = bool(context_ok and not reasons)
            tag = f"research_{direction.lower()}_{mode.lower()}"
            if accepted:
                forward_by_side[side]["tags"].append(tag)
                profile.count("research_entry/accepted/" + direction + "/" + mode)
            else:
                profile.count("research_entry/rejected/" + direction + "/" + mode)
                for reason in reasons:
                    profile.count("research_entry/reason/" + reason)
            engine.emit(
                "entry_hypotheses", state, flow["ts"],
                direction=direction, side=side, hypothesis=mode,
                accepted=accepted, reasons=reasons,
                anchor=asdict(anchor) if anchor else None,
                distance_from_anchor_bps=distance_bps,
                trend=state.trend, flow=flow, snapshot=snapshot,
            )


def reentry_research(engine, state, flow, snapshot, forward_by_side):
    """Log richer re-entry hypotheses without changing the live PAPER rule."""
    profile = engine.profiles[state.symbol]
    for model, book in state.books.items():
        watch = book.watch
        if not watch:
            continue
        side = watch["side"]
        direction = "LONG" if side == 1 else "SHORT"
        anchor = engine._anchor(state, side)
        correction_bps = max(
            0.0,
            (watch["exit_price"] - flow["price"]) / watch["exit_price"] * 10000
            if side == 1 else
            (flow["price"] - watch["exit_price"]) / watch["exit_price"] * 10000,
        )
        own_control = engine._control(flow, side)
        opposite_control = engine._control(flow, -side)
        own_accel = flow["buy_acceleration"] if side == 1 else flow["sell_acceleration"]
        opposite_accel = flow["sell_acceleration"] if side == 1 else flow["buy_acceleration"]
        own_absorption = flow["buy_absorption"] if side == 1 else flow["sell_absorption"]
        local_intact = bool(anchor and anchor.ident == watch["local_id"] and not anchor.invalidated)
        trend_side = 1 if state.trend == "UPTREND" else -1 if state.trend == "DOWNTREND" else 0
        structure_ok = trend_side in (0, side)
        reasons = []
        if not local_intact:
            reasons.append("ORIGINAL_LOCAL_LOST")
        if correction_bps <= 0:
            reasons.append("NO_CORRECTION_DEPTH")
        if not own_control:
            reasons.append("ORIGINAL_CONTROL_NOT_RETURNED")
        if own_accel is None or own_accel <= 0:
            reasons.append("ORIGINAL_FLOW_NOT_ACCELERATING")
        if own_absorption:
            reasons.append("ORIGINAL_SIDE_ABSORBED")
        if not structure_ok:
            reasons.append("STRUCTURE_OPPOSES_REENTRY")
        accepted = not reasons
        if accepted:
            forward_by_side[side]["tags"].append("research_reentry_ready_" + model)
            profile.count("research_reentry/ready/" + model)
        else:
            profile.count("research_reentry/rejected/" + model)
            for reason in reasons:
                profile.count("research_reentry/reason/" + reason)
        engine.emit(
            "reentry_hypotheses", state, flow["ts"],
            model=model, direction=direction, side=side,
            accepted=accepted, reasons=reasons,
            correction_depth_bps=correction_bps,
            correction_duration_seconds=max(0.0, flow["ts"] - watch.get("started_ts", flow["ts"])),
            original_exit_mfe_usd=watch.get("exit_mfe"),
            original_exit_mae_usd=watch.get("exit_mae"),
            own_control=own_control, opposite_control=opposite_control,
            own_acceleration=own_accel, opposite_acceleration=opposite_accel,
            local_intact=local_intact, structure_ok=structure_ok,
            snapshot=snapshot,
        )


def emit_microstructure_research(engine, state, flow, snapshot):
    """Persist price-response and observable large-participant proxies."""
    engine.emit(
        "price_response", state, flow["ts"],
        buy_notional=flow["buy_notional"], sell_notional=flow["sell_notional"],
        imbalance=flow["imbalance"], imbalance_change=flow["imbalance_change"],
        buy_response_bps=flow["buy_response_bps"],
        sell_response_bps=flow["sell_response_bps"],
        buy_efficiency_bps_per_10k=flow["buy_efficiency_bps_per_10k"],
        sell_efficiency_bps_per_10k=flow["sell_efficiency_bps_per_10k"],
        net_buy_efficiency=flow["net_buy_efficiency"],
        net_sell_efficiency=flow["net_sell_efficiency"],
        move_bps=flow["move_bps"], internal_move_bps=flow["internal_move_bps"],
        buy_absorption=flow["buy_absorption"], sell_absorption=flow["sell_absorption"],
        snapshot=snapshot,
    )
    events = []
    if flow["large_trade_count"]:
        events.append("LARGE_TRADE_CLUSTER")
    if flow["notional_z"] >= engine.config.absorption_z:
        events.append("VOLUME_BURST")
    if flow["intensity_z"] is not None and flow["intensity_z"] >= engine.config.absorption_z:
        events.append("INTENSITY_BURST")
    if flow["average_size_z"] >= engine.config.absorption_z:
        events.append("AVERAGE_SIZE_ANOMALY")
    if flow["buy_absorption"]:
        events.append("BUY_ABSORPTION")
    if flow["sell_absorption"]:
        events.append("SELL_ABSORPTION")
    if flow["move_bps"] > flow["price_scale_bps"] and flow["imbalance"] < 0:
        events.append("EFFICIENT_MINORITY_BUY_RESPONSE")
    if flow["move_bps"] < -flow["price_scale_bps"] and flow["imbalance"] > 0:
        events.append("EFFICIENT_MINORITY_SELL_RESPONSE")
    if not events:
        return
    engine.emit(
        "large_participant_events", state, flow["ts"],
        observable_only=True,
        actor_identity="UNKNOWN",
        events=events, flow=flow,
        market_context=state.market_context or None,
        snapshot=snapshot,
    )
