"""Strict offline readers. Bar timestamps are *availability*, not bucket starts.

Archive ``ts`` and ``ts_ms`` columns denote bucket starts unless ``start_ms``
is explicit. Universal minute archive ``ts`` is Unix seconds (verified in
scripts/universal_data.py on the source research ref); modern epoch seconds
in that unqualified column are converted. Explicit *_ms fields stay milliseconds.
Canonical output always includes start_ms, interval_ms, ts_ms.
Missing observations are never replaced with synthetic trades or zero flow.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator


class DataError(ValueError):
    """Input violates a documented market-data contract."""


def number(value, name: str, *, optional=False, nonnegative=False):
    if value is None or value == "":
        if optional:
            return None
        raise DataError(f"missing {name}")
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise DataError(f"invalid {name}") from exc
    if not math.isfinite(value) or (nonnegative and value < 0):
        raise DataError(f"nonfinite or negative {name}")
    return value


def timestamp_ms(value, *, seconds=False) -> int:
    """Decimal conversion avoids float rounding in raw executed timestamps."""
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0:
            raise InvalidOperation
        if seconds:
            n *= 1000
        # Millisecond truncation is intentional for higher-resolution trades.
        return int(n)
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise DataError("invalid timestamp") from exc


def _open(path: str | Path):
    path = Path(path)
    return gzip.open(path, "rt", encoding="utf-8", newline="") if path.suffix == ".gz" else path.open(encoding="utf-8", newline="")


def records(path: str | Path) -> Iterator[dict]:
    """Read CSV or JSONL, including gzip; reject malformed rows loudly."""
    path = Path(path)
    ext = path.with_suffix("").suffix if path.suffix == ".gz" else path.suffix
    with _open(path) as stream:
        if ext in (".jsonl", ".ndjson"):
            for line, text in enumerate(stream, 1):
                if not text.strip():
                    continue
                try:
                    row = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise DataError(f"{path.name}:{line}: malformed JSON") from exc
                if not isinstance(row, dict):
                    raise DataError(f"{path.name}:{line}: expected object")
                yield row
        else:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise DataError(f"{path.name}: no CSV header")
            for row in reader:
                if None in row:
                    raise DataError(f"{path.name}: extra CSV fields")
                yield row


def canonical_bar(row: dict, interval_ms=60_000) -> dict:
    interval = timestamp_ms(row.get("interval_ms", interval_ms))
    if interval <= 0:
        raise DataError("interval_ms must be positive")
    canonical = "start_ms" in row
    raw_start = row.get("start_ms", row.get("ts", row.get("ts_ms")))
    numeric_start = timestamp_ms(raw_start)
    seconds = (not canonical and 'ts' in row and
               1_000_000_000 <= numeric_start < 100_000_000_000)
    start = timestamp_ms(raw_start,seconds=seconds)
    if start % interval:
        raise DataError("bar start is not aligned to interval")
    end = start + interval
    available = timestamp_ms(row.get("available_at_ms", row.get("ts_ms", end) if canonical else end))
    if available < end:
        raise DataError("bar became available before close")
    out = dict(row)
    out.update(start_ms=start, interval_ms=interval, ts_ms=available, bar_end_ms=end)
    for key in ("open", "high", "low", "close"):
        out[key] = number(row.get(key), key, nonnegative=True)
        if out[key] <= 0:
            raise DataError("nonpositive price")
    if not out["low"] <= min(out["open"], out["close"]) <= max(out["open"], out["close"]) <= out["high"]:
        raise DataError("inconsistent OHLC")
    for key in ("buy_notional", "sell_notional"):
        out[key] = number(row.get(key), key, optional=True, nonnegative=True)
    for key in ("buy_qty", "sell_qty", "buy_count", "sell_count", "trade_count"):
        if key in row:
            out[key] = number(row[key], key, optional=True, nonnegative=True)
    out["flow_observed"] = out["buy_notional"] is not None and out["sell_notional"] is not None
    return out


def read_bars(path: str | Path, interval_ms=60_000) -> Iterator[dict]:
    previous = None
    for row in records(path):
        bar = canonical_bar(row, interval_ms)
        if previous is not None:
            if bar["start_ms"] < previous["bar_end_ms"]:
                raise DataError("duplicate, reordered, or overlapping bars in file")
            if bar["ts_ms"] <= previous["ts_ms"]:
                raise DataError("nonmonotonic bar availability")
        bar["gap_before"] = previous is not None and bar["start_ms"] > previous["bar_end_ms"]
        previous = bar
        yield bar


def load_bars(paths: Iterable[str | Path] | str | Path, interval_ms=60_000) -> list[dict]:
    """Merge archive parts; identical boundary duplicates allowed, conflicts rejected."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    by_start = {}
    for path in paths:
        for row in read_bars(path, interval_ms):
            key = row["start_ms"]
            old = by_start.get(key)
            if old is not None:
                fields = ("ts_ms", "interval_ms", "open", "high", "low", "close", "buy_notional", "sell_notional")
                if any(old[k] != row[k] for k in fields):
                    raise DataError("conflicting duplicate bar across archives")
            else:
                by_start[key] = row
    rows = [by_start[t] for t in sorted(by_start)]
    previous = None
    for row in rows:
        if previous is not None and (row["start_ms"] < previous["bar_end_ms"] or row["ts_ms"] <= previous["ts_ms"]):
            raise DataError("overlapping intervals or reordered availability across archives")
        row["gap_before"] = previous is not None and row["start_ms"] != previous["bar_end_ms"]
        previous = row
    return rows


def aggregate_raw_trades(path: str | Path, interval_ms=5000, end_ms=None) -> Iterator[dict]:
    """Stream true executed order into OHLC/flow bars, never infer intrabar paths.

    Without an explicit archive completeness boundary, the final bucket is not
    emitted: a last execution alone does not establish that its interval ended.
    Empty buckets stay gaps. Reordered raw rows fail instead of being silently
    sorted; equal timestamps retain the source ordering, which may be ambiguous.
    """
    if interval_ms <= 0:
        raise DataError("interval_ms must be positive")
    previous_ts = None
    bucket = None
    for row in records(path):
        raw_ts = row.get("timestamp", row.get("time", row.get("execTime", row.get("T"))))
        # Bybit archives express seconds as decimal; websocket T is milliseconds.
        try:
            seconds = Decimal(str(raw_ts)) < Decimal("1000000000000")
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise DataError("invalid raw execution timestamp") from exc
        t = timestamp_ms(raw_ts, seconds=seconds)
        if previous_ts is not None and t < previous_ts:
            raise DataError("raw executions are out of order")
        previous_ts = t
        if end_ms is not None and t >= end_ms:
            raise DataError("raw execution at or beyond completeness boundary")
        price = number(row.get("price", row.get("p")), "trade price", nonnegative=True)
        qty = number(row.get("size", row.get("qty", row.get("v"))), "trade quantity", nonnegative=True)
        if price <= 0 or qty <= 0:
            raise DataError("nonpositive execution")
        side = str(row.get("side", row.get("S", ""))).lower()
        if side not in ("buy", "sell"):
            raise DataError("unknown execution side")
        start = t // interval_ms * interval_ms
        if bucket is not None and start != bucket["start_ms"]:
            yield canonical_bar(bucket, interval_ms)
            bucket = None
        if bucket is None:
            bucket = dict(start_ms=start, interval_ms=interval_ms, ts_ms=start + interval_ms,
                          open=price, high=price, low=price, close=price,
                          buy_notional=0.0, sell_notional=0.0, trade_count=0,
                          first_trade_ms=t, last_trade_ms=t, source="raw_executed_trades")
        bucket["high"] = max(bucket["high"], price)
        bucket["low"] = min(bucket["low"], price)
        bucket["close"] = price
        bucket[side + "_notional"] += price * qty
        bucket["trade_count"] += 1
        bucket["last_trade_ms"] = t
    if bucket is not None and end_ms is not None and bucket["start_ms"] + interval_ms <= end_ms:
        yield canonical_bar(bucket, interval_ms)


def load_snapshots(path: str | Path) -> list[dict]:
    rows = []
    previous = None
    for row in records(path):
        item = dict(row)
        item["ts_ms"] = timestamp_ms(row.get("ts_ms"))
        if previous is not None and item["ts_ms"] <= previous:
            raise DataError("duplicate or reordered forward snapshots")
        previous = item["ts_ms"]
        rows.append(item)
    return rows


def replay_raw_frames(path: str | Path) -> Iterator[dict]:
    """Replay exact captured forward frames using their *receipt* clock.

    Yields one feature snapshot per received frame, with no invented events in
    intervals between frames. Receipt sequence is independent of exchange seq.
    Older collectors lacking raw frame capture cannot use this adapter.
    """
    from .research import LiveState
    now_ms = 0
    state = LiveState(clock=lambda: now_ms/1000)
    previous_sequence = 0
    for envelope in records(path):
        ts = timestamp_ms(envelope.get("received_ts_ms"))
        seq = timestamp_ms(envelope.get("receipt_sequence"))
        if ts < now_ms or seq != previous_sequence+1:
            raise DataError("raw forward receipt time regressed or sequence missing")
        now_ms, previous_sequence = ts, seq
        try:
            msg = json.loads(envelope["raw_text"])
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            raise DataError("raw forward frame missing or malformed") from exc
        state.on_subscription(msg)
        topic = msg.get("topic", "")
        if topic.startswith("orderbook."):
            state.on_book(msg)
        elif topic.startswith("publicTrade."):
            state.on_trade(msg)
        elif topic.startswith("allLiquidation."):
            state.on_liq(msg)
        elif topic.startswith("tickers."):
            state.on_ticker(msg)
        out = state.snapshot()
        out["receipt_sequence"] = seq
        yield out


def join_asof(bars: Iterable[dict], samples: Iterable[dict], max_age_ms=2000) -> Iterator[dict]:
    """Join received forward features only after receipt and with bounded age.

    Canonical price/flow fields always come from bars. Cumulative 60s snapshot
    flow is never added to interval flow. OI needs its own source timestamp to
    establish freshness; receipt of a snapshot cannot refresh a stale OI value.
    """
    if max_age_ms < 0:
        raise DataError("negative freshness tolerance")
    iterator = iter(samples)
    pending = next(iterator, None)
    current = None
    prev_sample = None
    prev_bar = None
    protected = {"ts_ms", "start_ms", "bar_end_ms", "interval_ms", "open", "high", "low", "close", "buy_notional", "sell_notional", "gap_before", "flow_observed"}
    for bar in bars:
        t = bar["ts_ms"]
        if prev_bar is not None and t <= prev_bar:
            raise DataError("bars not ordered by availability")
        prev_bar = t
        while pending is not None and pending["ts_ms"] <= t:
            if prev_sample is not None and pending["ts_ms"] <= prev_sample:
                raise DataError("samples not strictly ordered")
            current = pending
            prev_sample = pending["ts_ms"]
            pending = next(iterator, None)
        out = dict(bar)
        out["forward_snapshot_ts_ms"] = None
        if current is not None and 0 <= t-current["ts_ms"] <= max_age_ms:
            for key, value in current.items():
                if key not in protected:
                    out[key] = value
            out["forward_snapshot_ts_ms"] = current["ts_ms"]
        yield out


def join_historical_oi(bars: Iterable[dict], path: str | Path, publication_lag_ms=300_000,
                       sampling_interval_ms=300_000) -> Iterator[dict]:
    """As-of REST OI join with an explicit, conservative publication assumption.

    Archived exchange sample times are not historical receipt times. Unless an
    explicit available_at_ms column exists, availability is ASSUMED to be sample
    time + publication_lag_ms, and this assumption travels with every output row.
    A five-minute series cannot establish sub-five-minute OI changes.
    """
    if publication_lag_ms < 0 or sampling_interval_ms <= 0:
        raise DataError("invalid historical OI timing contract")
    oi = []
    previous = None
    previous_available = None
    for row in records(path):
        source_t = timestamp_ms(row.get("ts_ms", row.get("ts", row.get("timestamp"))))
        value = number(row.get("open_interest", row.get("openInterest")), "historical OI", nonnegative=True)
        if value <= 0:
            raise DataError("nonpositive historical OI")
        known = row.get("available_at_ms") not in (None, "")
        available = timestamp_ms(row["available_at_ms"]) if known else source_t+publication_lag_ms
        if available < source_t:
            raise DataError("OI availability precedes sample time")
        if previous is not None and (source_t <= previous or available <= previous_available):
            raise DataError("reordered or conflicting historical OI samples")
        previous, previous_available = source_t, available
        oi.append(dict(oi_ts_ms=source_t, open_interest=value, oi_available_at_ms=available,
                       oi_sampling_interval_ms=sampling_interval_ms,
                       oi_publication_lag_ms=available-source_t,
                       oi_availability_assumed=not known))
    i = 0
    current = None
    previous_bar = None
    for bar in bars:
        t = bar["ts_ms"]
        if previous_bar is not None and t <= previous_bar:
            raise DataError("OI join bars not ordered by availability")
        previous_bar = t
        while i < len(oi) and oi[i]["oi_available_at_ms"] <= t:
            current = oi[i]
            i += 1
        out = dict(bar)
        if current is not None:
            out.update(current)
        yield out


def provenance(path: str | Path) -> dict:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def coverage(rows: list[dict]) -> dict:
    missing = 0
    for a, b in zip(rows, rows[1:]):
        missing += max(0, b["start_ms"] - a["bar_end_ms"])
    return dict(rows=len(rows), start_ms=rows[0]["start_ms"] if rows else None,
                end_ms=rows[-1]["bar_end_ms"] if rows else None,
                gap_duration_ms=missing, flow_rows=sum(bool(r["flow_observed"]) for r in rows),
                exact_intrabar_order_available=False)
