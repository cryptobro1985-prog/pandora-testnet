"""Crash-safe JSON checkpoints for the isolated Caterpillar research engine."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict
from datetime import datetime, timezone

from .h1 import H1Bar, H1Tracker
from .model import Local, Position, Trade
from .output import Metric, Profile
from .research_layer import MultiLocalResearch


CHECKPOINT_SCHEMA = 1
DEDUP_IDS_IN_CHECKPOINT = 20000


def _metric_dump(metric):
    return {
        "n": metric.n, "mean": metric.mean, "m2": metric.m2,
        "minimum": metric.minimum, "maximum": metric.maximum,
        "recent": list(metric.recent),
    }


def _metric_load(row):
    metric = Metric()
    metric.n = int(row.get("n", 0))
    metric.mean = float(row.get("mean", 0.0))
    metric.m2 = float(row.get("m2", 0.0))
    metric.minimum = row.get("minimum")
    metric.maximum = row.get("maximum")
    metric.recent = deque(row.get("recent", []), maxlen=2048)
    return metric


def _profile_dump(profile):
    return {
        "metrics": {k: _metric_dump(v) for k, v in profile.metrics.items()},
        "counts": profile.counts,
        "outcomes": profile.outcomes,
        "daily": {k: dict(v) for k, v in profile.daily.items()},
        "evicted_days": profile.evicted_days,
        "first": profile.first, "last": profile.last,
    }


def _profile_load(row):
    p = Profile()
    p.metrics = {k: _metric_load(v) for k, v in row.get("metrics", {}).items()}
    p.counts = dict(row.get("counts", {}))
    p.outcomes = dict(row.get("outcomes", {}))
    p.daily = {k: OrderedDict(v.items()) for k, v in row.get("daily", {}).items()}
    p.evicted_days = dict(row.get("evicted_days", {}))
    p.first = row.get("first")
    p.last = row.get("last")
    return p


def _h1_dump(h1):
    return {
        "lookback": h1.lookback, "next_ident": h1.next_ident,
        "history": [asdict(x) for x in h1.history],
        "pending": {k: asdict(v) for k, v in h1.pending.items()},
        "current": asdict(h1.current) if h1.current else None,
        "current_complete": h1.current_complete,
        "latest_available_ts": h1.latest_available_ts,
        "discontinuity": h1.discontinuity,
    }


def _h1_load(row):
    tracker = H1Tracker(int(row.get("lookback", 4)), int(row.get("next_ident", 0)))
    tracker.history = deque(
        (H1Bar(**x) for x in row.get("history", [])),
        maxlen=max(128, tracker.lookback + 2),
    )
    tracker.pending = {k: Local(**v) for k, v in row.get("pending", {}).items()}
    tracker.current = H1Bar(**row["current"]) if row.get("current") else None
    tracker.current_complete = bool(row.get("current_complete", False))
    tracker.latest_available_ts = row.get("latest_available_ts")
    tracker.discontinuity = bool(row.get("discontinuity", False))
    return tracker


def _state_dump(state):
    ids = list(state.ids.keys())[-DEDUP_IDS_IN_CHECKPOINT:]
    return {
        "block": [asdict(x) for x in state.block],
        "history": list(state.history),
        "locals": {k: [asdict(x) for x in v] for k, v in state.locals.items()},
        "ids": ids,
        "books": {
            model: {
                "position": asdict(book.position) if book.position else None,
                "pending": book.pending, "watch": book.watch,
                "break_streak": book.break_streak,
                "anchor_invalidated": book.anchor_invalidated,
            }
            for model, book in state.books.items()
        },
        "forecasts": list(state.forecasts),
        "post_exits": list(state.post_exits),
        "seq": state.seq, "local_seq": state.local_seq,
        "order_seq": state.order_seq, "last_ts": state.last_ts,
        "last_price": state.last_price, "trend": state.trend,
        "break_counts": state.break_counts, "sweeps": state.sweeps,
        "candle_last": state.candle_last,
        "candle_history": list(state.candle_history),
        "defenses": {k: list(v) for k, v in state.defenses.items()},
        "continuity_broken": state.continuity_broken,
        "h1": _h1_dump(state.h1),
        "h1_confirmations": [asdict(x) for x in state.h1_confirmations],
        "market_context": state.market_context,
        "market_context_last_emit": state.market_context_last_emit,
        "research_locals": state.research_locals.state_dict() if state.research_locals else None,
    }


def _state_load(state, row, config):
    state.block = [Trade(**x) for x in row.get("block", [])]
    state.history = deque(row.get("history", []), maxlen=config.baseline_blocks)
    state.locals = {
        "LOW": deque((Local(**x) for x in row.get("locals", {}).get("LOW", [])), maxlen=2),
        "HIGH": deque((Local(**x) for x in row.get("locals", {}).get("HIGH", [])), maxlen=2),
    }
    state.ids = OrderedDict((x, None) for x in row.get("ids", []))
    for model, book in state.books.items():
        saved = row.get("books", {}).get(model, {})
        book.position = Position(**saved["position"]) if saved.get("position") else None
        book.pending = saved.get("pending")
        book.watch = saved.get("watch")
        book.break_streak = int(saved.get("break_streak", 0))
        book.anchor_invalidated = bool(saved.get("anchor_invalidated", False))
    state.forecasts = deque(row.get("forecasts", []))
    state.post_exits = deque(row.get("post_exits", []))
    state.seq = int(row.get("seq", 0))
    state.local_seq = int(row.get("local_seq", 0))
    state.order_seq = int(row.get("order_seq", 0))
    state.last_ts = row.get("last_ts")
    state.last_price = row.get("last_price")
    state.trend = row.get("trend", "RANGE")
    state.break_counts = dict(row.get("break_counts", {"LOW": 0, "HIGH": 0}))
    state.sweeps = dict(row.get("sweeps", {}))
    state.candle_last = row.get("candle_last")
    state.candle_history = deque(row.get("candle_history", []), maxlen=8)
    state.defenses = {k: tuple(v) for k, v in row.get("defenses", {}).items()}
    state.continuity_broken = bool(row.get("continuity_broken", False))
    state.h1 = _h1_load(row.get("h1", {}))
    state.h1_confirmations = [Local(**x) for x in row.get("h1_confirmations", [])]
    state.candidate = max(state.h1.pending.values(), key=lambda x: (x.candle_close_ts or 0, x.ident)) if state.h1.pending else None
    state.market_context = dict(row.get("market_context", {}))
    state.market_context_last_emit = dict(row.get("market_context_last_emit", {}))
    tracker = MultiLocalResearch(state.symbol)
    if row.get("research_locals"):
        tracker.load_state(row["research_locals"])
    state.research_locals = tracker


def dump_engine(engine, reason="periodic", extra=None):
    return {
        "checkpoint_schema": CHECKPOINT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "config_sha256": engine.config.digest,
        "symbols": list(engine.states),
        "split_ts": engine.split_ts,
        "record_raw": engine.record_raw,
        "coverage": engine.coverage,
        "states": {symbol: _state_dump(state) for symbol, state in engine.states.items()},
        "profiles": {symbol: _profile_dump(profile) for symbol, profile in engine.profiles.items()},
        "last_hourly_snapshot_wall": engine.last_hourly_snapshot_wall,
        "extra": extra or {},
        "output_offsets": engine.output.stream_offsets(),
    }


def restore_engine(engine, payload):
    if payload.get("checkpoint_schema") != CHECKPOINT_SCHEMA:
        raise ValueError("Unsupported checkpoint schema")
    if payload.get("config_sha256") != engine.config.digest:
        raise ValueError("Checkpoint/config mismatch")
    if tuple(payload.get("symbols", [])) != tuple(engine.states):
        raise ValueError("Checkpoint symbol universe mismatch")
    for symbol, row in payload.get("states", {}).items():
        if symbol not in engine.states:
            raise ValueError("Checkpoint contains unexpected symbol")
        _state_load(engine.states[symbol], row, engine.config)
    engine.profiles = {
        symbol: _profile_load(payload.get("profiles", {}).get(symbol, {}))
        for symbol in engine.states
    }
    engine.coverage = list(payload.get("coverage", []))
    engine.last_hourly_snapshot_wall = payload.get("last_hourly_snapshot_wall")
    engine.record_raw = bool(payload.get("record_raw", engine.record_raw))
    return payload.get("extra", {})
