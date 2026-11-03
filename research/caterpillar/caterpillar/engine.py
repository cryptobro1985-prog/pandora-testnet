from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
import math
import time

from .h1 import H1Tracker

from .model import Config, Local, Position, SYMBOLS, Trade, features
from .output import Profile
from .research_layer import MultiLocalResearch, dual_side_entry_research, emit_microstructure_research, reentry_research
from .reporting import persist_status, synthesize


@dataclass
class Book:
    position: Position | None = None
    pending: dict | None = None
    watch: dict | None = None
    break_streak: int = 0
    anchor_invalidated: bool = False


@dataclass
class State:
    symbol: str
    block: list = field(default_factory=list)
    history: deque = field(default_factory=deque)
    candidate: Local | None = None
    locals: dict = field(default_factory=lambda: {"LOW": deque(maxlen=2), "HIGH": deque(maxlen=2)})
    ids: OrderedDict = field(default_factory=OrderedDict)
    books: dict = field(default_factory=dict)
    forecasts: deque = field(default_factory=deque)
    post_exits: deque = field(default_factory=deque)
    seq: int = 0
    local_seq: int = 0
    order_seq: int = 0
    last_ts: float | None = None
    last_price: float | None = None
    trend: str = "RANGE"
    break_counts: dict = field(default_factory=lambda: {"LOW": 0, "HIGH": 0})
    sweeps: dict = field(default_factory=dict)
    candle_last: float | None = None
    candle_history: deque = field(default_factory=lambda: deque(maxlen=8))
    defenses: dict = field(default_factory=dict)
    continuity_broken: bool = False
    h1: H1Tracker | None = None
    h1_confirmations: list = field(default_factory=list)
    research_locals: MultiLocalResearch | None = None
    market_context: dict = field(default_factory=dict)
    market_context_last_emit: dict = field(default_factory=dict)


class ResearchEngine:
    def __init__(self, output, config=None, symbols=SYMBOLS, split_ts=None, record_raw=False):
        self.config = config or Config()
        self.output = output
        self.split_ts = split_ts
        self.record_raw = record_raw
        if not symbols or len(set(symbols)) != len(symbols) or not set(symbols) <= set(SYMBOLS):
            raise ValueError("Only unique fixed-universe symbols are allowed")
        self.states = {s: State(s, history=deque(maxlen=self.config.baseline_blocks),
                                books={m: Book() for m in self.config.exit_models},
                                h1=H1Tracker(self.config.h1_lookback_bars)) for s in symbols}
        for symbol, state in self.states.items():
            state.research_locals = MultiLocalResearch(symbol)
        self.profiles = {s: Profile() for s in symbols}
        self.finished = False
        self.coverage = []
        self.last_checkpoint_wall = time.monotonic()
        self.last_status_wall = time.monotonic()
        self.last_hourly_snapshot_wall = None
        self.resume_extra = {}

    def emit(self, stream, s, ts, **data):
        self.output.emit(stream, {"ts": ts, "symbol": s.symbol, "event_seq": s.seq, **data})

    def checkpoint(self, reason="periodic", extra=None):
        from .stateio import dump_engine
        payload = dump_engine(self, reason=reason, extra=extra or self.resume_extra)
        self.output.save_json("checkpoint.json", payload)
        self.last_checkpoint_wall = time.monotonic()
        return payload

    def restore_checkpoint(self):
        import json
        from .stateio import restore_engine
        path = self.output.root/"checkpoint.json"
        if not path.is_file():
            raise ValueError("checkpoint.json not found")
        payload = json.loads(path.read_text())
        self.resume_extra = restore_engine(self, payload)
        self.last_checkpoint_wall = time.monotonic()
        self.last_status_wall = time.monotonic()
        return self.resume_extra

    def maybe_checkpoint(self, reason="periodic"):
        if time.monotonic() - self.last_checkpoint_wall >= self.config.checkpoint_seconds:
            self.checkpoint(reason)

    def maybe_status(self, reason="heartbeat"):
        now_mono = time.monotonic()
        now_wall = time.time()
        if now_mono - self.last_status_wall >= self.config.status_seconds:
            persist_status(self, now_wall, reason=reason, hourly=False)
            self.last_status_wall = now_mono
        if (self.last_hourly_snapshot_wall is None
                or now_wall - self.last_hourly_snapshot_wall >= self.config.hourly_snapshot_seconds):
            persist_status(self, now_wall, reason="hourly", hourly=True)
            self.last_hourly_snapshot_wall = now_wall

    def on_market_context(self, symbol, ts, context):
        if symbol not in self.states:
            raise ValueError("Market context symbol outside configured universe")
        s = self.states[symbol]
        kind = context.get("kind")
        if kind not in ("orderbook_l1", "liquidation"):
            raise ValueError("Unknown market context kind")
        s.market_context[kind] = context
        last = s.market_context_last_emit.get(kind, 0.0)
        # L1 can arrive at very high frequency. Keep latest state always, but
        # persist at most 1 Hz per symbol. Liquidations are sparse and always emitted.
        if kind == "liquidation" or ts - last >= 1.0:
            self.emit("market_context", s, ts, context=context)
            s.market_context_last_emit[kind] = ts

    def quality(self, symbol, ts, reason, **data):
        s = self.states[symbol]
        self.profiles[symbol].count("quality/"+reason)
        self.emit("data_quality", s, ts, reason=reason, **data)

    def phase(self, ts):
        return "evaluation" if self.split_ts is not None and ts >= self.split_ts else "discovery"

    def _stage(self, s, local, ts, stage, **details):
        self.profiles[s.symbol].count("local/"+stage)
        self.emit("locals", s, ts, stage=stage, local=asdict(local), **details)

    def gap(self, symbol, ts, reason):
        """Missing observations censor positions and labels; never invent a gap fill."""
        s = self.states[symbol]
        s.continuity_broken = True
        if self.record_raw:
            self.emit("raw_trades", s, ts, event="GAP", reason=reason)
        self.quality(symbol, ts, reason)
        for model, book in s.books.items():
            if book.position:
                self.emit("trades", s, ts, action="CENSORED", model=model, reason=reason,
                          position=asdict(book.position), counted_as_closed=False)
                self.profiles[symbol].count(model+"/censored")
            book.position = book.pending = book.watch = None
            book.break_streak = 0
            book.anchor_invalidated = False
        for row in s.forecasts:
            self.emit("hypothesis_outcomes", s, ts, status="CENSORED", reason=reason, candidate=row)
        for row in s.post_exits:
            self.emit("post_exit", s, ts, status="CENSORED", reason=reason, observation=row)
        if reason == "evaluation_boundary":
            s.research_locals = MultiLocalResearch(s.symbol)
            for group in s.locals.values():
                for local in group:
                    if not local.invalidated:
                        local.invalidated, local.status = True, "INVALIDATED"
                        self._stage(s, local, ts, "INVALIDATED", reason=reason)
            s.h1 = H1Tracker(self.config.h1_lookback_bars, next_ident=s.local_seq)
            s.locals = {"LOW": deque(maxlen=2), "HIGH": deque(maxlen=2)}
            s.candidate = None
            s.trend = "RANGE"
        else:
            s.h1.mark_gap()
            if s.research_locals is not None:
                s.research_locals.gap(
                    ts, lambda stream, ts, **data: self.emit(stream, s, ts, **data),
                    reason=reason)
        s.h1_confirmations.clear()
        s.block.clear()
        s.history.clear()
        s.forecasts.clear()
        s.post_exits.clear()
        s.break_counts = {"LOW": 0, "HIGH": 0}
        s.sweeps.clear()
        s.defenses.clear()
        s.candle_history.clear()
        s.market_context.clear()

    def _apply_h1(self, s, events, observed_at, seeded=False):
        for local, stage, reason in events:
            s.local_seq = max(s.local_seq, local.ident)
            self._stage(s, local, observed_at,
                        stage, reason=reason, timeframe="1h", seeded=seeded, observed_at=observed_at)
            if stage == "CONFIRMED":
                s.locals[local.kind].append(local)
                if not seeded:
                    s.h1_confirmations.append(local)
        s.candidate = max(s.h1.pending.values(), key=lambda x: (x.candle_close_ts, x.ident)) if s.h1.pending else None

    def seed_h1(self, symbol, candle, as_of=None):
        """Seed verified closed H1 bars. This method never executes a PAPER decision."""
        if self.finished:
            raise RuntimeError("Run already finished")
        s = self.states[symbol]
        observed = time.time() if as_of is None else float(as_of)
        events, accepted = s.h1.seed(candle, observed)
        if accepted:
            if self.record_raw:
                self.emit("raw_trades", s, observed, event="H1_SEED", candle=candle, as_of=observed)
            self._apply_h1(s, events, observed, seeded=True)
            if s.research_locals is not None and s.h1.history:
                latest_flow = s.history[-1] if s.history else None
                s.research_locals.on_closed_bar(
                    s.h1.history[-1], observed, latest_flow,
                    lambda stream, ts, **data: self.emit(stream, s, ts, **data),
                    self.profiles[symbol], self.phase(observed), seeded=True)
        return accepted

    def on_trade(self, trade: Trade):
        if self.finished:
            raise RuntimeError("Run already finished")
        if trade.symbol not in self.states:
            raise ValueError("Symbol outside configured universe")
        s, cfg = self.states[trade.symbol], self.config
        if not trade.valid():
            self.quality(trade.symbol, s.last_ts or 0, "invalid_trade")
            self.gap(trade.symbol, s.last_ts or 0, "invalid_trade_gap")
            return False
        if s.h1.latest_available_ts is not None and trade.ts < s.h1.latest_available_ts:
            self.quality(trade.symbol, trade.ts, "trade_precedes_h1_availability")
            return False
        if trade.trade_id in s.ids:
            self.quality(trade.symbol, trade.ts, "duplicate")
            return False
        # Remember rejected late IDs too. The feed adapter reorders within a bounded watermark.
        s.ids[trade.trade_id] = None
        if len(s.ids) > 100000:
            s.ids.popitem(last=False)
        if s.last_ts is not None and trade.ts < s.last_ts:
            self.quality(trade.symbol, trade.ts, "late_trade", last_accepted_ts=s.last_ts)
            self.gap(trade.symbol, s.last_ts, "late_trade_gap")
            return False
        if not s.continuity_broken and s.last_ts is not None and trade.ts-s.last_ts > cfg.gap_seconds:
            self.gap(trade.symbol, trade.ts, "observation_gap")
        # The split is an actual held-out restart: no open positions/forward labels cross it.
        if not s.continuity_broken and self.split_ts and s.last_ts is not None and s.last_ts < self.split_ts <= trade.ts:
            self.gap(trade.symbol, trade.ts, "evaluation_boundary")
        s.seq += 1
        s.last_ts, s.last_price = trade.ts, trade.price
        s.continuity_broken = False
        profile = self.profiles[trade.symbol]
        if profile.first is None:
            profile.first = trade.ts
        profile.last = trade.ts
        profile.count("accepted_trades")
        profile.add("trade_size_usd", trade.notional)
        profile.add("trade_quantity", trade.quantity)
        if self.record_raw:
            self.emit("raw_trades", s, trade.ts, trade=asdict(trade))
        # Close an observed H1 and apply its structure before any pending fill.
        before_h1 = len(s.h1.history)
        h1_events = s.h1.tick(trade)
        self._apply_h1(s, h1_events, trade.ts)
        if len(s.h1.history) > before_h1 and s.research_locals is not None:
            latest_flow = s.history[-1] if s.history else None
            s.research_locals.on_closed_bar(
                s.h1.history[-1], trade.ts, latest_flow,
                lambda stream, ts, **data: self.emit(stream, s, ts, **data),
                profile, self.phase(trade.ts), seeded=False)
        # Execute prior decisions on a later timestamp, never retrospectively at a local extremum.
        for model, book in s.books.items():
            if book.pending and book.pending["action"] != "CLOSE":
                order = book.pending
                if s.seq-order.get("event_seq", s.seq) > cfg.block_trades or trade.ts-order["ts"] > cfg.gap_seconds:
                    self._forbid_reentry_opportunity(s, model, order, "SIGNAL_EXPIRED_BEFORE_FILL")
                    self.emit("rejected_signals", s, trade.ts, action=order["action"], model=model,
                              reasons=["SIGNAL_EXPIRED_BEFORE_FILL"], signal=order)
                    book.pending = None
            try:
                if book.pending and trade.ts > book.pending["ts"]:
                    self._fill(s, model, book, trade)
                if book.position:
                    book.position.mark(trade.price, trade.ts, cfg.fee_bps, cfg.slippage_bps)
            except (ValueError, OverflowError, ZeroDivisionError):
                # Numeric-domain failure is missing usable evidence, never an
                # infinite gain/loss or a zero-quantity successful paper fill.
                self.gap(trade.symbol, trade.ts, "numerical_position_error")
                break
            if book.watch and (trade.price-book.watch["exit_price"])*book.watch["side"] < 0:
                book.watch["correction_seen"] = True
        self._future_labels(s, trade)
        self._tick_sweeps(s, trade)
        s.block.append(trade)
        if len(s.block) == cfg.block_trades:
            c = features(s.block, s.history, cfg)
            self._evaluate(s, c)
            s.history.append(c)
            s.block.clear()
        self.maybe_checkpoint("accepted_trade")
        self.maybe_status("running")
        return True

    def _tick_sweeps(self, s, trade):
        for kind, group in s.locals.items():
            if not group or group[-1].invalidated:
                continue
            local = group[-1]
            beyond = trade.price < local.price if kind == "LOW" else trade.price > local.price
            sweep = s.sweeps.get(kind)
            if sweep is not None and sweep["local_id"] != local.ident:
                s.sweeps.pop(kind, None)
                sweep = None
            if beyond and sweep is None:
                s.sweeps[kind] = {"local_id": local.ident, "ts": trade.ts, "price": trade.price}
                self.emit("structure", s, trade.ts, event="SWEEP", kind=kind, local_id=local.ident)
            elif not beyond and sweep is not None:
                self.emit("structure", s, trade.ts, event="FALSE_BREAK", kind=kind, local_id=local.ident, sweep=sweep)
                self.profiles[s.symbol].count("structure/FALSE_BREAK")
                s.sweeps.pop(kind, None)

    def _local_structure(self, s, c):
        cfg = self.config
        confirmed = list(s.h1_confirmations)
        s.h1_confirmations.clear()
        threshold = max(cfg.local_floor_bps, c["price_scale_bps"]*cfg.local_vol_multiplier)
        events = []
        for kind, group in s.locals.items():
            if not group or group[-1].invalidated:
                continue
            anchor = group[-1]
            beyond = c["price"] < anchor.price if kind == "LOW" else c["price"] > anchor.price
            break_side = -1 if kind == "LOW" else 1
            s.break_counts[kind] = s.break_counts[kind]+1 if beyond and self._control(c, break_side) else 0
            if s.break_counts[kind] >= cfg.transfer_blocks:
                anchor.invalidated = True
                anchor.status = "INVALIDATED"
                self._stage(s, anchor, c["ts"], "INVALIDATED", reason="STRUCTURE_BREAK", flow=c)
                events.append("STRUCTURE_BREAK")
                s.sweeps.pop(kind, None)
        previous_trend = s.trend
        lows, highs = s.locals["LOW"], s.locals["HIGH"]
        if len(lows) == len(highs) == 2:
            if lows[-1].price > lows[0].price and highs[-1].price > highs[0].price and not lows[-1].invalidated:
                s.trend = "UPTREND"
            elif lows[-1].price < lows[0].price and highs[-1].price < highs[0].price and not highs[-1].invalidated:
                s.trend = "DOWNTREND"
            else:
                s.trend = "RANGE"
        if previous_trend != s.trend and previous_trend != "RANGE":
            events.append("REVERSAL")
        if c["buy_absorption"] or c["sell_absorption"]:
            events.append("ABSORPTION")
        dominant_accel = c["buy_acceleration"] if c["imbalance"] > 0 else c["sell_acceleration"]
        if dominant_accel is not None and dominant_accel < 0 and abs(c["move_bps"]) < c["price_scale_bps"]*.5:
            events.append("EXHAUSTION")
        if abs(c["move_bps"]) >= threshold:
            events.append("IMPULSE")
        trend_side = 1 if s.trend == "UPTREND" else -1 if s.trend == "DOWNTREND" else 0
        if trend_side and c["move_bps"]*trend_side < 0 and "STRUCTURE_BREAK" not in events:
            events.append("PULLBACK")
        for event in events:
            self.profiles[s.symbol].count("structure/"+event)
        self.emit("structure", s, c["ts"], trend=s.trend, events=events, confirmed_local_id=confirmed[0].ident if len(confirmed) == 1 else None,
                  confirmed_local_ids=[local.ident for local in confirmed], timeframe="1h")
        return confirmed, events

    def _control(self, c, side):
        return c["imbalance"]*side >= self.config.control_imbalance and c["move_bps"]*side > 0

    def _anchor(self, s, side):
        group = s.locals["LOW" if side == 1 else "HIGH"]
        return group[-1] if group and not group[-1].invalidated else None

    def _snapshot(self, s, c):
        return {"flow": c, "trend": s.trend, "locals": {k: [asdict(x) for x in v] for k, v in s.locals.items()},
                "forming": asdict(s.candidate) if s.candidate else None,
                "h1": {"timeframe": "1h", "closed_bars": len(s.h1.history),
                       "current": asdict(s.h1.current) if s.h1.current else None,
                       "current_complete": s.h1.current_complete,
                       "pending": {kind: asdict(local) for kind, local in s.h1.pending.items()}},
                "research_locals": {
                    "pending": [asdict(x) for x in s.research_locals.pending.values()]
                    if s.research_locals else []
                },
                "market_context": s.market_context or None,
                "phase": self.phase(c["ts"]),
                "config_sha256": self.config.digest}

    def _evaluate(self, s, c):
        profile, cfg = self.profiles[s.symbol], self.config
        profile.count("flow_blocks")
        for key in ("notional", "average_trade_size", "imbalance", "trade_intensity", "buy_efficiency_bps_per_10k",
                    "sell_efficiency_bps_per_10k", "buy_acceleration", "sell_acceleration", "move_bps", "large_trade_count"):
            profile.add("flow/"+key, c[key])
        confirmed, events = self._local_structure(s, c)
        for kind in ("LOW", "HIGH"):
            anchor = self._anchor(s, 1 if kind == "LOW" else -1)
            if anchor and abs(c["price"]/anchor.price-1)*10000 <= c["price_scale_bps"]:
                profile.count("near_"+kind)
                profile.add("near_"+kind+"/imbalance", c["imbalance"])
                profile.add("near_"+kind+"/price_response_bps", c["move_bps"])
                if c["buy_absorption"] or c["sell_absorption"]:
                    prior_id, count = s.defenses.get(kind, (None, 0))
                    count = count+1 if prior_id == anchor.ident else 1
                    s.defenses[kind] = (anchor.ident, count)
                    if count >= 2:
                        events.append("REPEATED_DEFENSE")
                        profile.count("near_"+kind+"/repeated_defense")
                        self.emit("structure", s, c["ts"], event="REPEATED_DEFENSE", local_id=anchor.ident, observations=count)
        self.emit("flow_events", s, c["ts"], flow=c, events=events)
        snapshot = self._snapshot(s, c)
        # Forward labels are quarantined, never passed into a decision. They share
        # the causal snapshot used for entry/rejection, so actual Caterpillar
        # conjunctions can be studied rather than only isolated generic flow tags.
        forward_by_side = {}
        for side in (-1, 1):
            tags = ["SHORT" if side == -1 else "LONG"]
            if self._control(c, side): tags.append("control")
            if c["large_trade_count"]: tags.append("large_trades")
            if c["notional_z"] >= cfg.absorption_z: tags.append("volume_burst")
            if c["buy_absorption"]: tags.append("buy_absorption")
            if c["sell_absorption"]: tags.append("sell_absorption")
            if c["intensity_z"] is not None and c["intensity_z"] >= cfg.absorption_z: tags.append("intensity_burst")
            if c["average_size_z"] >= cfg.absorption_z: tags.append("average_size_anomaly")
            if c["move_bps"]*side > c["price_scale_bps"] and c["imbalance"]*side < 0: tags.append("efficient_minority_flow")
            tags.extend(events)
            anchor = self._anchor(s, side)
            if anchor and (c["price"]-anchor.price)*side > 0:
                tags.append("confirmed_low" if side == 1 else "confirmed_high")
            accel = c["buy_acceleration"] if side == 1 else c["sell_acceleration"]
            trend_side = 1 if s.trend == "UPTREND" else -1 if s.trend == "DOWNTREND" else 0
            # Predeclared causal conjunctions. These are evaluated as hypotheses,
            # not searched exhaustively after seeing PnL.
            if self._control(c, side) and accel is not None and accel > 0:
                tags.append("combo_control_acceleration")
                if anchor:
                    tags.append("combo_local_control_acceleration")
                if trend_side == side:
                    tags.append("combo_trend_control_acceleration")
                if c["large_trade_count"]:
                    tags.append("combo_control_acceleration_large_trade")
                if c["notional_z"] >= cfg.absorption_z:
                    tags.append("combo_control_acceleration_volume_burst")
            if c["imbalance"]*side < 0 and c["move_bps"]*side > c["price_scale_bps"]:
                tags.append("combo_minority_flow_directional_response")
            row = {"seq": s.seq, "ts": c["ts"], "side": side, "signal_price": c["price"],
                   "entry": None, "tags": list(dict.fromkeys(tags)), "phase": self.phase(c["ts"]),
                   "mfe_bps": 0.0, "mae_bps": 0.0, "snapshot": snapshot}
            forward_by_side[side] = row
            s.forecasts.append(row)
        emit_microstructure_research(self, s, c, snapshot)
        dual_side_entry_research(self, s, c, snapshot, forward_by_side)
        reentry_research(self, s, c, snapshot, forward_by_side)
        for model, book in s.books.items():
            if book.pending:
                continue
            if book.position:
                p = book.position
                p.bars += 1
                own, opposite = self._control(c, p.side), self._control(c, -p.side)
                p.opposite_streak = p.opposite_streak+1 if opposite else 0
                own_accel = c["buy_acceleration"] if p.side == 1 else c["sell_acceleration"]
                weakening = own_accel is not None and own_accel < 0 and c["move_bps"]*p.side <= 0
                p.weakening_streak = p.weakening_streak+1 if weakening else 0
                # A position may refer to an older local than the latest symbol
                # local. Its breach must be evaluated against its own anchor,
                # and a confirmed invalidation remains true after a rebound.
                beyond_anchor = (c["price"]-p.local_price)*p.side < 0
                book.break_streak = book.break_streak+1 if beyond_anchor and opposite else 0
                book.anchor_invalidated = book.anchor_invalidated or book.break_streak >= cfg.transfer_blocks
                broken = book.anchor_invalidated
                opposite_local = any((local.kind == "HIGH") == (p.side == 1) for local in confirmed)
                predicates = {
                    "flow_weakening": p.weakening_streak >= cfg.transfer_blocks,
                    "opposite_flow": p.opposite_streak >= cfg.transfer_blocks,
                    "price_reversal": p.opposite_streak >= cfg.transfer_blocks and c["move_bps"]*p.side <= -c["price_scale_bps"],
                    "absorption": (c["buy_absorption"] if p.side == 1 else c["sell_absorption"]) and weakening,
                    "mfe_recoil": p.mfe > 0 and p.mfe-p.current >= abs(p.quantity*p.entry*c["price_scale_bps"]/10000) and opposite and weakening,
                    "local_invalidation": broken,
                    "opposite_local": opposite_local,
                    "structure_break": broken,
                }
                predicates["combined"] = broken or opposite_local or (predicates["opposite_flow"] and (weakening or predicates["mfe_recoil"]))
                giveback = p.mfe-p.current
                self.emit("mfe_analysis", s, c["ts"], model=model, position_id=p.ident, current_gross_usd=p.current,
                          mfe_usd=p.mfe, mae_usd=p.mae, mfe_ts=p.mfe_ts, giveback_usd=giveback,
                          anchor_break_streak=book.break_streak, anchor_invalidated=book.anchor_invalidated,
                          giveback_ratio=giveback/p.mfe if p.mfe > 0 else None, exit_predicates=predicates, snapshot=snapshot)
                self.emit("exit_hypotheses", s, c["ts"], model=model, position_id=p.ident,
                          predicates=predicates, own_control=own, opposite_control=opposite,
                          weakening=weakening, current_gross_usd=p.current,
                          mfe_usd=p.mfe, mae_usd=p.mae, giveback_usd=giveback,
                          snapshot=snapshot)
                self.emit("positions", s, c["ts"], action="MARK", model=model,
                          position=asdict(p), exit_predicates=predicates)
                if predicates[model]:
                    reasons = [key for key, value in predicates.items() if value and key != "combined"]
                    book.pending = {"action": "CLOSE", "ts": c["ts"], "reasons": reasons, "snapshot": snapshot}
                    self.emit("signals", s, c["ts"], action="EXIT", model=model, reasons=reasons, snapshot=snapshot)
                else:
                    label = "MICRO_COUNTER_FLOW" if opposite and p.opposite_streak < cfg.transfer_blocks else "PULLBACK" if c["move_bps"]*p.side < 0 else "HOLD"
                    hold_tag = "research_hold_"+label.lower()+"_"+model
                    forward_by_side[p.side]["tags"].append(hold_tag)
                    profile.count("research_hold/"+label+"/"+model)
                    self.emit("signals", s, c["ts"], action="HOLD", label=label, model=model, position_id=p.ident,
                              research_tag=hold_tag, snapshot=snapshot)
                continue
            anchors = [x[-1] for x in s.locals.values() if x and not x[-1].invalidated]
            newest = max(anchors, key=lambda x: x.confirmed_ts) if anchors else None
            side = (1 if newest.kind == "LOW" else -1) if newest else (1 if c["imbalance"] >= 0 else -1)
            if book.watch:
                side = book.watch["side"]
            anchor = self._anchor(s, side)
            reasons = []
            if newest and sum(local.confirmed_ts == newest.confirmed_ts for local in anchors) > 1:
                reasons.append("AMBIGUOUS_H1_LOCALS")
            if len(s.history) < cfg.warmup_blocks: reasons.append("WARMUP")
            if not anchor: reasons.append("NO_VALID_CONFIRMED_LOCAL")
            elif (c["price"]-anchor.price)*side <= 0: reasons.append("BEYOND_LOCAL")
            if not self._control(c, side): reasons.append("NO_PRICE_RESPONSIVE_CONTROL")
            accel = c["buy_acceleration"] if side == 1 else c["sell_acceleration"]
            if accel is None or accel <= 0: reasons.append("NO_ACCELERATION")
            if c["buy_absorption"] if side == 1 else c["sell_absorption"]: reasons.append("OWN_ABSORPTION")
            if (s.trend == "DOWNTREND" and side == 1) or (s.trend == "UPTREND" and side == -1): reasons.append("COUNTER_TREND")
            if book.watch:
                if not anchor or anchor.ident != book.watch["local_id"]: reasons.append("ORIGINAL_LOCAL_LOST")
                if newest and ((newest.kind == "LOW") != (side == 1)):
                    reasons.append("OPPOSITE_LOCAL_CONFIRMED")
                if not book.watch["correction_seen"]: reasons.append("NO_CORRECTION_OBSERVED")
                if book.watch["expires_seq"] < s.seq: reasons.append("REENTRY_HORIZON_EXPIRED")
            action = "REENTRY" if book.watch else "OPEN"
            if reasons:
                forward_by_side[side]["tags"].append("rejected_"+model)
                forward_by_side[side]["tags"].extend("rejected_"+model+"_"+reason for reason in reasons)
                self.emit("rejected_signals", s, c["ts"], action=action, side=side, model=model,
                          label="FORBIDDEN_REENTRY" if book.watch else "REJECTED", reasons=reasons, snapshot=snapshot)
                profile.count(model+"/"+("FORBIDDEN_REENTRY" if book.watch else "rejected"))
                if book.watch and any(x in reasons for x in ("ORIGINAL_LOCAL_LOST", "REENTRY_HORIZON_EXPIRED", "OPPOSITE_LOCAL_CONFIRMED")):
                    book.watch = None
            else:
                book.pending = {"action": action, "ts": c["ts"], "event_seq": s.seq, "side": side, "local_id": anchor.ident,
                                "local_price": anchor.price, "snapshot": snapshot,
                                "parent_exit": book.watch["exit_id"] if book.watch else None}
                if book.watch:
                    for observation in s.post_exits:
                        if observation["exit_id"] == book.watch["exit_id"]:
                            if not observation["eligible_reentry_seen"]:
                                observation["eligible_signal_ts"] = c["ts"]
                                observation["eligible_fill_price"] = None
                                observation["eligible_max_net_bps"] = None
                                observation["eligible_forbidden_reason"] = None
                            observation["eligible_reentry_seen"] = True
                self.emit("signals", s, c["ts"], action=action, side=side, model=model, snapshot=snapshot)
                forward_by_side[side]["tags"].append(action.lower()+"_"+model)
        for row in forward_by_side.values():
            row["tags"] = list(dict.fromkeys(row["tags"]))

    def _forbid_reentry_opportunity(self, s, model, order, reason):
        """A forbidden/expired fill is not an executable missed opportunity."""
        if order["action"] != "REENTRY":
            return
        for observation in s.post_exits:
            if observation["exit_id"] == order.get("parent_exit") and observation["model"] == model:
                observation["eligible_reentry_seen"] = False
                observation["eligible_signal_ts"] = None
                observation["eligible_fill_price"] = None
                observation["eligible_max_net_bps"] = None
                observation["eligible_forbidden_reason"] = reason

    def _fill(self, s, model, book, trade):
        order, cfg = book.pending, self.config
        book.pending = None
        if order["action"] == "CLOSE":
            p = book.position
            p.mark(trade.price, trade.ts, cfg.fee_bps, cfg.slippage_bps)
            price = trade.price*(1-p.side*cfg.slippage_bps/10000)
            gross = (price-p.entry)*p.side*p.quantity
            fees = (p.entry+price)*p.quantity*cfg.fee_bps/10000
            net = gross-fees
            row = {"action": "CLOSE", "model": model, "position": asdict(p), "exit_price": price,
                   "exit_ts": trade.ts, "signal_ts": order["ts"], "gross_usd": gross, "fees_usd": fees,
                   "net_usd_before_funding": net, "net_bps": net/(p.entry*p.quantity)*10000,
                   "mfe_capture_ratio": gross/p.mfe if p.mfe > 0 else None,
                   "net_mfe_capture_ratio": net/p.net_mfe if p.net_mfe > 0 else None,
                   "mfe_giveback_usd": p.mfe-gross, "reasons": order["reasons"], "exit_snapshot": order["snapshot"]}
            numeric_fields = ("exit_price", "gross_usd", "fees_usd", "net_usd_before_funding", "net_bps",
                              "mfe_capture_ratio", "net_mfe_capture_ratio", "mfe_giveback_usd")
            if any(row[key] is not None and not math.isfinite(row[key]) for key in numeric_fields):
                raise ValueError("Unrepresentable paper close")
            self.emit("trades", s, trade.ts, **row)
            self.emit("positions", s, trade.ts, action="CLOSE", model=model, close=row)
            profile = self.profiles[s.symbol]
            profile.count(model+"/closed")
            for key, value in (("net_usd", net), ("mfe", p.mfe), ("mae", p.mae), ("giveback", p.mfe-gross)):
                profile.add(model+"/"+key, value)
            direction = "LONG" if p.side == 1 else "SHORT"
            profile.outcome(self.phase(trade.ts)+"/exit/"+model+"/"+direction, row["net_bps"], ts=trade.ts)
            if p.reentry:
                label = "GOOD_REENTRY" if net > 0 else "BAD_REENTRY"
                profile.count(model+"/"+label)
                self.emit("hypothesis_outcomes", s, trade.ts, status="COMPLETE", label=label, model=model, position_id=p.ident, net_usd=net)
            exit_id = p.ident+"/exit"
            s.post_exits.append({"exit_id": exit_id, "model": model, "side": p.side, "price": trade.price,
                                 "exit_seq": s.seq, "exit_ts": trade.ts, "max_continuation_bps": 0.0,
                                 "max_adverse_bps": 0.0, "reentered": False, "eligible_reentry_seen": False,
                                 "eligible_signal_ts": None, "eligible_fill_price": None,
                                 "eligible_max_net_bps": None})
            if not any(r in order["reasons"] for r in ("local_invalidation", "structure_break", "opposite_local")):
                book.watch = {"side": p.side, "local_id": p.local_id, "exit_id": exit_id, "exit_price": trade.price,
                              "started_ts": trade.ts, "exit_mfe": p.mfe, "exit_mae": p.mae,
                              "correction_seen": False, "expires_seq": s.seq+cfg.post_exit_trades}
            else:
                book.watch = None
            book.position = None
            book.break_streak = 0
            book.anchor_invalidated = False
        else:
            anchor = self._anchor(s, order["side"])
            anchors = [group[-1] for group in s.locals.values() if group and not group[-1].invalidated]
            newest = max(anchors, key=lambda local: local.confirmed_ts) if anchors else None
            if newest and sum(local.confirmed_ts == newest.confirmed_ts for local in anchors) > 1:
                self._forbid_reentry_opportunity(s, model, order, "AMBIGUOUS_H1_LOCALS")
                self.emit("rejected_signals", s, trade.ts, action=order["action"], model=model,
                          reasons=["AMBIGUOUS_H1_LOCALS"], signal=order)
                return
            if newest and ((newest.kind == "LOW") != (order["side"] == 1)):
                self._forbid_reentry_opportunity(s, model, order, "OPPOSITE_LOCAL_BEFORE_FILL")
                self.emit("rejected_signals", s, trade.ts, action=order["action"], model=model,
                          reasons=["OPPOSITE_LOCAL_BEFORE_FILL"], signal=order)
                book.watch = None
                return
            if not anchor or anchor.ident != order["local_id"] or (trade.price-order["local_price"])*order["side"] <= 0:
                self._forbid_reentry_opportunity(s, model, order, "LOCAL_INVALID_BEFORE_FILL")
                self.emit("rejected_signals", s, trade.ts, action=order["action"], model=model, reasons=["LOCAL_INVALID_BEFORE_FILL"], signal=order)
                return
            price = trade.price*(1+order["side"]*cfg.slippage_bps/10000)
            quantity = cfg.notional/price if math.isfinite(price) and price > 0 else 0
            if not math.isfinite(price) or price <= 0 or not math.isfinite(quantity) or quantity <= 0 or not math.isfinite(price*quantity) or price*quantity <= 0:
                self._forbid_reentry_opportunity(s, model, order, "UNREPRESENTABLE_FILL")
                self.emit("rejected_signals", s, trade.ts, action=order["action"], model=model,
                          reasons=["UNREPRESENTABLE_FILL"], signal=order)
                return
            s.order_seq += 1
            p = Position(f"{s.symbol}/{model}/{s.order_seq}", order["side"], price, trade.ts, quantity,
                         order["local_id"], order["local_price"], order["snapshot"],
                         reentry=order["action"] == "REENTRY", parent_exit=order["parent_exit"], mfe_ts=trade.ts)
            p.mark(trade.price, trade.ts, cfg.fee_bps, cfg.slippage_bps)
            book.position = p
            book.break_streak = 0
            book.anchor_invalidated = False
            if p.parent_exit:
                for watch in s.post_exits:
                    if watch["exit_id"] == p.parent_exit:
                        watch["reentered"] = True
            book.watch = None
            self.profiles[s.symbol].count(model+"/"+order["action"])
            self.emit("trades", s, trade.ts, action=order["action"], model=model, position=asdict(p), signal_ts=order["ts"])
            self.emit("positions", s, trade.ts, action=order["action"], model=model, position=asdict(p), signal_ts=order["ts"])
            # A permitted signal can still be rejected or expire before its
            # execution. Only a successful PAPER fill qualifies its queued
            # forward observation as an executable entry conjunction.
            signal_tag = order["action"].lower()+"_"+model
            filled_tag = "filled_"+signal_tag
            for observation in s.forecasts:
                if (observation["ts"] == order["ts"] and observation["side"] == order["side"]
                        and ("event_seq" not in order or observation["seq"] == order["event_seq"])
                        and signal_tag in observation["tags"] and filled_tag not in observation["tags"]):
                    observation["tags"].append(filled_tag)

    def _future_labels(self, s, trade):
        cfg = self.config
        remaining = deque()
        for row in s.forecasts:
            if row["entry"] is None and s.seq-row["seq"] > cfg.outcome_trades:
                self.emit("hypothesis_outcomes", s, trade.ts, status="CENSORED", reason="no_later_timestamp_fill", candidate=row)
                continue
            if row["entry"] is None and trade.ts > row["ts"]:
                row["entry"] = trade.price*(1+row["side"]*cfg.slippage_bps/10000)
                row["entry_seq"] = s.seq
            if row["entry"] is not None:
                excursion = (trade.price/row["entry"]-1)*row["side"]*10000
                row["mfe_bps"] = max(row.get("mfe_bps", 0.0), excursion)
                row["mae_bps"] = min(row.get("mae_bps", 0.0), excursion)
            if row["entry"] is not None and s.seq-row["entry_seq"] >= cfg.outcome_trades:
                exit_price = trade.price*(1-row["side"]*cfg.slippage_bps/10000)
                net = ((exit_price-row["entry"])*row["side"]-(exit_price+row["entry"])*cfg.fee_bps/10000)/row["entry"]*10000
                capture = net/row["mfe_bps"] if row.get("mfe_bps", 0) > 0 else None
                self.emit("hypothesis_outcomes", s, trade.ts, status="COMPLETE", candidate=row,
                          net_bps=net, mfe_bps=row.get("mfe_bps"), mae_bps=row.get("mae_bps"),
                          mfe_capture_ratio=capture)
                direction = "LONG" if row["side"] == 1 else "SHORT"
                for tag in row["tags"]:
                    profile = self.profiles[s.symbol]
                    profile.outcome(row["phase"]+"/feature/"+direction+"/"+tag, net, ts=row["ts"])
                    metric_prefix = "pattern/"+direction+"/"+tag+"/"
                    profile.add(metric_prefix+"net_bps", net)
                    profile.add(metric_prefix+"mfe_bps", row.get("mfe_bps"))
                    profile.add(metric_prefix+"mae_bps", row.get("mae_bps"))
                    profile.add(metric_prefix+"mfe_capture_ratio", capture)
            else:
                remaining.append(row)
        s.forecasts = remaining
        remaining = deque()
        for row in s.post_exits:
            move = (trade.price/row["price"]-1)*row["side"]*10000
            row["max_continuation_bps"] = max(row["max_continuation_bps"], move)
            row["max_adverse_bps"] = min(row["max_adverse_bps"], move)
            # A move that preceded re-entry eligibility was not an opportunity
            # to re-enter. Measure the hypothetical opportunity with the same
            # next-timestamp fill and costs as the causal entry model.
            if row["eligible_reentry_seen"] and row.get("eligible_signal_ts") is not None and trade.ts > row["eligible_signal_ts"]:
                if row.get("eligible_fill_price") is None:
                    row["eligible_fill_price"] = trade.price*(1+row["side"]*cfg.slippage_bps/10000)
                entry = row["eligible_fill_price"]
                liquidation = trade.price*(1-row["side"]*cfg.slippage_bps/10000)
                net_bps = ((liquidation-entry)*row["side"]-(liquidation+entry)*cfg.fee_bps/10000)/entry*10000
                if math.isfinite(net_bps):
                    prior_max = row.get("eligible_max_net_bps")
                    row["eligible_max_net_bps"] = max(prior_max, net_bps) if prior_max is not None else net_bps
            if s.seq-row["exit_seq"] >= cfg.post_exit_trades:
                cost = 2*(cfg.fee_bps+cfg.slippage_bps)
                missed = (row["eligible_reentry_seen"] and not row["reentered"]
                          and row.get("eligible_max_net_bps") is not None and row["eligible_max_net_bps"] > 0)
                label = "EARLY_EXIT_CANDIDATE" if row["max_continuation_bps"] > cost else "FAVORABLE_EXIT_CANDIDATE" if row["max_adverse_bps"] < -cost else "INCONCLUSIVE"
                self.emit("post_exit", s, trade.ts, status="COMPLETE", **row, final_return_bps=move, label=label, missed_reentry_candidate=missed)
                if missed:
                    self.profiles[s.symbol].count(row["model"]+"/MISSED_REENTRY")
            else:
                remaining.append(row)
        s.post_exits = remaining

    def on_candle(self, symbol, candle):
        """Explicit fallback. Closed OHLCV bars do not enter the trade/flow state machine."""
        s = self.states[symbol]
        ts = float(candle["available_ts"])
        if s.candle_last is not None and ts <= s.candle_last:
            self.quality(symbol, ts, "duplicate_or_late_candle")
            return
        s.candle_last = ts
        prior = list(s.candle_history)
        events = []
        if prior:
            if candle["low"] < min(x["low"] for x in prior): events.append("NEW_LOWER_LOW_UNCONFIRMED")
            if candle["high"] > max(x["high"] for x in prior): events.append("NEW_HIGHER_HIGH_UNCONFIRMED")
            if candle["close"] > max(x["high"] for x in prior): events.append("CLOSE_ABOVE_PRIOR_RANGE")
            if candle["close"] < min(x["low"] for x in prior): events.append("CLOSE_BELOW_PRIOR_RANGE")
        s.candle_history.append(candle)
        self.profiles[symbol].count("ohlcv_only_bars")
        self.emit("candles", s, ts, candle=candle, structure_observations=events, flow_available=False, paper_entries_enabled=False)

    def finish(self, status="completed"):
        if self.finished:
            return
        open_books = {}
        for symbol, s in self.states.items():
            open_books[symbol] = {m: {"position": asdict(b.position) if b.position else None,
                                      "pending": b.pending, "watch": b.watch} for m, b in s.books.items()}
            for model, b in s.books.items():
                if b.position:
                    self.emit("trades", s, s.last_ts, action="END_MARK", model=model, position=asdict(b.position), counted_as_closed=False)
                if b.pending:
                    self.emit("signals", s, s.last_ts, action="UNFILLED_AT_END", model=model, pending=b.pending)
            for row in s.forecasts:
                self.emit("hypothesis_outcomes", s, s.last_ts, status="CENSORED", reason="end_of_run", candidate=row)
            for row in s.post_exits:
                self.emit("post_exit", s, s.last_ts, status="CENSORED", reason="end_of_run", observation=row)
        summary = {"status": status, "config_sha256": self.config.digest, "coverage": self.coverage,
                   "split_ts": self.split_ts, "open_books_not_realized": open_books,
                   "profiles": {s: p.result() for s, p in self.profiles.items()},
                   "portfolio": "Independent fixed-notional hypothetical books; no shared equity, compounding or portfolio leverage claim.",
                   "quality_policy": "Censor and warm up after missing data; reject duplicates/late events; do not invent flow.",
                   "unproven": ["profitability", "optimal thresholds", "actor identity", "funding", "market impact", "full archive coverage"]}
        strategy = synthesize(self, status)
        summary["strategy_synthesis"] = strategy
        self.output.save_json("strategy_synthesis.json", strategy)
        persist_status(self, time.time(), reason="final", hourly=True)
        summary["aggregate_exit_books"] = {}
        for model in self.config.exit_models:
            samples = [p.metrics[model+"/net_usd"] for p in self.profiles.values() if model+"/net_usd" in p.metrics]
            try:
                total = math.fsum(sample.mean*sample.n for sample in samples)
                total_status = "finite" if math.isfinite(total) else "unrepresentable"
                if total_status != "finite":
                    total = None
            except (ValueError, OverflowError):
                total, total_status = None, "unrepresentable"
            summary["aggregate_exit_books"][model] = {
                "closed_trades": sum(x.n for x in samples),
                "net_usd_before_funding": total, "financial_total_status": total_status,
                "note": "Sum of independent fixed-notional research books, not a shared-capital portfolio return"}
        self.output.finish(self.profiles, summary, self.config, status)
        self.finished = True
