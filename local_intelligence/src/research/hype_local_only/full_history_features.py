"""Small, causal feature matrix built only from retained raw historical channels.

Historical receipt clocks do not exist in these files. Minute trade bars are
assumed finalized at their end; mark/index bars require their end plus one
second, and OI/funding observations require their source timestamp plus one
second. Those are replay assumptions, never fabricated receive timestamps.
No candidate snapshots, labels, L50 books, or liquidation values are read.
"""
from __future__ import annotations

from collections import deque
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
from zipfile import BadZipFile

import numpy as np

MINUTE = 60_000
HOUR = 60 * MINUTE
AUX_LAG_MS = 1_000
WINDOWS = (1, 3, 5, 15, 60, 180, 360)
SCHEMA_VERSION = 1
SOURCE_FILES = {
    "minutes": "history_30d_local116/compact_1m.jsonl.gz",
    "mark": "historical_gaps/mark_1m.jsonl.gz",
    "index": "historical_gaps/index_1m.jsonl.gz",
    "oi": "historical_gaps/open_interest_5m.jsonl.gz",
    "funding": "historical_gaps/funding.jsonl.gz",
}
AUX_SPECS = {
    "mark": ("close", MINUTE, 3 * MINUTE),
    "index": ("close", MINUTE, 3 * MINUTE),
    "oi": ("open_interest", 0, 15 * MINUTE),
    "funding": ("funding_rate", 0, 12 * HOUR),
}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float("nan")
    return float(value) if np.isfinite(value) else float("nan")


def _column(rows: list[dict[str, Any]], name: str) -> np.ndarray:
    return np.asarray([_number(row.get(name)) for row in rows], dtype=np.float64)


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing sum; callers independently enforce complete, observed windows."""
    sums = np.r_[0.0, np.cumsum(np.nan_to_num(values, nan=0.0))]
    starts = np.maximum(0, np.arange(len(values)) + 1 - window)
    return sums[1:] - sums[starts]


def _rolling_extreme(values: np.ndarray, window: int, high: bool) -> np.ndarray:
    result = np.full(len(values), np.nan)
    queue: deque[int] = deque()
    for i, value in enumerate(values):
        while queue and queue[0] <= i - window:
            queue.popleft()
        if np.isfinite(value):
            while queue and ((values[queue[-1]] <= value) if high else (values[queue[-1]] >= value)):
                queue.pop()
            queue.append(i)
        if queue:
            result[i] = values[queue[0]]
    return result


def _divide(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.divide(a, b, out=np.full(np.broadcast_shapes(a.shape, b.shape), np.nan), where=b != 0)


class FullHistoryFeatures:
    """Retained history with ordered minute rows and a <=200-column float32 matrix.

    ``root`` may be the standalone local_intelligence directory or its repository.
    ``features[i]`` is evaluated at ``ends[i]``. ``at(ts_ms)`` uses the latest
    completed minute and redoes auxiliary joins at the exact requested clock.
    Missing/stale measurements are NaN and have separate observability flags.
    ``source_clocks(ts_ms)`` supplies exact integer clocks for audit; float32
    features contain ages in seconds rather than imprecise epoch milliseconds.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not (self.root / "artifacts").is_dir() and (self.root / "local_intelligence/artifacts").is_dir():
            self.root /= "local_intelligence"
        self.artifacts = self.root / "artifacts"
        self.directory = self.artifacts / "full_history_research"
        self.paths = {key: self.artifacts / relative for key, relative in SOURCE_FILES.items()}
        if not self.paths["minutes"].is_file():
            raise FileNotFoundError(self.paths["minutes"])
        self.source_hashes = {
            str(path.relative_to(self.artifacts)): _sha256(path) if path.is_file() else None
            for path in self.paths.values()
        }
        self.minutes = sorted(_read_rows(self.paths["minutes"]), key=lambda row: int(row["start_ms"]))
        self.ends = np.asarray([int(row["start_ms"]) + MINUTE for row in self.minutes], dtype=np.int64)
        if not len(self.ends) or np.any(np.diff(self.ends) <= 0):
            raise ValueError("retained minute history must contain unique, increasing starts")
        self._minute_available = np.asarray([
            max(int(row["start_ms"]) + MINUTE, *(int(row[key]) for key in
                ("bar_end_ms", "ts_ms", "available_at_ms", "received_ts_ms", "source_ts_ms", "source_timestamp_ms")
                if row.get(key) is not None)) for row in self.minutes
        ], dtype=np.int64)
        self._aux = {name: self._load_aux(name) for name in AUX_SPECS}
        self._cache_key = {
            "schema_version": SCHEMA_VERSION,
            "implementation_sha256": _sha256(Path(__file__)),
            "source_hashes": self.source_hashes,
            "auxiliary_availability_lag_ms": AUX_LAG_MS,
        }
        self.cache_hit = self._read_cache()
        if not self.cache_hit:
            self._build()
            self._write_cache()
        self._name_index = {name: i for i, name in enumerate(self.names)}
        self.coverage = self._coverage()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._write_json(self.directory / "FEATURE_COVERAGE.json", self.coverage)

    @classmethod
    def from_records(cls, minutes: list[dict[str, Any]], aux: dict[str, list[dict[str, Any]]] | None = None):
        """In-memory replay using the same encoder, with no cache or file writes.

        Public auxiliary keys are ``mark``, ``index``, ``oi``, and ``funding``;
        records retain the saved channel schemas. This is a bounded batch
        factory, not an incremental live transport or receipt reconstruction.
        """
        instance = cls.__new__(cls)
        instance.minutes = sorted([dict(row) for row in minutes], key=lambda row: int(row["start_ms"]))
        instance.ends = np.asarray([int(row["start_ms"]) + MINUTE for row in instance.minutes], dtype=np.int64)
        if not len(instance.ends) or np.any(np.diff(instance.ends) <= 0):
            raise ValueError("minute records must contain unique, increasing starts")
        instance._minute_available = np.asarray([
            max(int(row["start_ms"]) + MINUTE, *(int(row[key]) for key in
                ("bar_end_ms", "ts_ms", "available_at_ms", "received_ts_ms", "source_ts_ms", "source_timestamp_ms")
                if row.get(key) is not None)) for row in instance.minutes
        ], dtype=np.int64)
        instance._aux = {name: instance._prepare_aux(name, (aux or {}).get(name, [])) for name in AUX_SPECS}
        instance.source_hashes = {}
        instance.cache_hit = False
        instance._build()
        instance._name_index = {name: i for i, name in enumerate(instance.names)}
        instance.coverage = instance._coverage()
        return instance

    def _load_aux(self, name: str) -> dict[str, Any]:
        return self._prepare_aux(name, _read_rows(self.paths[name]))

    @staticmethod
    def _prepare_aux(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        value_key, duration, _ = AUX_SPECS[name]
        rows = []
        for original in records:
            row = dict(original)
            source = int(row["ts_ms"])
            value = _number(row.get(value_key))
            received = row.get("received_ts_ms")
            if not np.isfinite(value) or (name != "funding" and value <= 0):
                continue
            if received is not None and int(received) < source:
                continue
            if duration and not all(np.isfinite(_number(row.get(k))) for k in ("open", "high", "low", "close")):
                continue
            available = max(source + duration + AUX_LAG_MS, int(received) if received is not None else 0,
                            int(row.get("available_at_ms", 0)))
            rows.append((source, available, row, received))
        rows.sort(key=lambda item: item[0])
        if any(a[0] >= b[0] for a, b in zip(rows, rows[1:])):
            raise ValueError(f"{name} history contains duplicate/non-increasing source clocks")
        # Retained feeds have monotonic availability; reject inconsistent clocks
        # rather than silently treating a future receipt as historical evidence.
        if any(a[1] > b[1] for a, b in zip(rows, rows[1:])):
            raise ValueError(f"{name} availability clocks must be monotonic")
        return {
            "rows": [item[2] for item in rows],
            "values": {key: _column([item[2] for item in rows], key) for key in
                       (("open", "high", "low", "close") if duration else (value_key,))},
            "source": np.asarray([item[0] for item in rows], dtype=np.int64),
            "available": np.asarray([item[1] for item in rows], dtype=np.int64),
            "received": [None if item[3] is None else int(item[3]) for item in rows],
            "received_known": np.asarray([item[3] is not None for item in rows]),
        }

    def _read_cache(self) -> bool:
        try:
            metadata = json.loads((self.directory / "FEATURE_METADATA.json").read_text())
            if metadata["cache_key"] != self._cache_key:
                return False
            with np.load(self.directory / "features.npz", allow_pickle=False) as archive:
                if not np.array_equal(archive["ends"], self.ends):
                    return False
                names = archive["names"].tolist()
                features = archive["features"]
                if features.dtype != np.float32 or features.shape != (len(self.ends), len(names)) or len(names) > 200:
                    return False
                self.names, self.features = names, features.copy()
                self._minute_valid = archive["minute_valid"].astype(bool)
            return True
        except (OSError, ValueError, KeyError, BadZipFile, json.JSONDecodeError):
            return False

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        temporary.replace(path)

    def _write_cache(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", dir=self.directory, delete=False) as handle:
            temporary = Path(handle.name)
            np.savez_compressed(handle, ends=self.ends, names=np.asarray(self.names),
                                features=self.features, minute_valid=self._minute_valid)
        temporary.replace(self.directory / "features.npz")
        self._write_json(self.directory / "FEATURE_METADATA.json", {
            "cache_key": self._cache_key, "rows": len(self.ends), "columns": len(self.names),
            "dtype": "float32", "names": self.names,
            "nan_policy": "unobserved, partial, invalid, or stale values remain NaN; observability flags are explicit",
            "clock_policy": "ages are numeric features; source_clocks(as_of_ms) preserves exact source/end/assumed-availability clocks",
        })

    def _build(self, as_of_ms: int | None = None) -> None:
        rows, n = self.minutes, len(self.ends)
        values = {key: _column(rows, key) for key in (
            "open", "high", "low", "close", "quantity", "turnover", "buy_notional", "sell_notional",
            "buy_count", "sell_count", "trade_count", "max_trade_notional", "flow_imbalance",
            "high_ts_ms", "low_ts_ms")}
        op, hi, lo, close = (values[key] for key in ("open", "high", "low", "close"))
        valid = np.ones(n, dtype=bool)
        for column in (op, hi, lo, close):
            valid &= np.isfinite(column) & (column > 0)
        valid &= (hi >= np.maximum(op, close)) & (lo <= np.minimum(op, close)) & (hi >= lo)
        valid &= np.asarray([not row.get("gap") and row.get("confirm") is not False for row in rows])
        valid &= np.asarray([int(row.get("bar_end_ms", int(row["start_ms"]) + MINUTE)) == int(row["start_ms"]) + MINUTE
                             and int(row["start_ms"]) % MINUTE == 0 for row in rows])
        valid &= np.asarray([
            not (row.get("received_ts_ms") is not None and any(
                row.get(key) is not None and int(row[key]) > int(row["received_ts_ms"])
                for key in ("source_ts_ms", "source_timestamp_ms"))) for row in rows])
        # Keep physical validity separate from observation availability: a real
        # candle normally arrives after its physical end, then becomes usable.
        self._minute_valid = valid.copy()
        valid &= self._minute_available <= (self.ends if as_of_ms is None else int(as_of_ms))
        flow_valid = valid & np.asarray([row.get("flow_observed") is True for row in rows])
        for key in ("quantity", "turnover", "buy_notional", "sell_notional", "buy_count", "sell_count",
                    "trade_count", "max_trade_notional"):
            flow_valid &= np.isfinite(values[key]) & (values[key] >= 0)
        cols: dict[str, np.ndarray] = {}

        def add(name: str, array: np.ndarray, mask: np.ndarray | None = None) -> None:
            array = np.asarray(array, dtype=np.float64)
            cols[name] = np.where(mask, array, np.nan) if mask is not None else array

        for key in ("open", "high", "low", "close"):
            add("m1__" + key, values[key], valid)
        for key in ("quantity", "turnover", "buy_notional", "sell_notional", "buy_count", "sell_count",
                    "trade_count", "max_trade_notional"):
            add("m1__" + key, values[key], flow_valid)
        total = values["buy_notional"] + values["sell_notional"]
        imbalance = _divide(values["buy_notional"] - values["sell_notional"], total)
        add("m1__flow_imbalance", imbalance, flow_valid)
        add("m1__observed", valid.astype(float))
        add("m1__flow_observed", flow_valid.astype(float))
        received_known = np.asarray([row.get("received_ts_ms") is not None for row in rows])
        add("m1__received_clock_known", received_known.astype(float))
        add("m1__source_time_only", (~received_known).astype(float))
        add("m1__age_s", np.zeros(n))
        body = (close / op - 1) * 10_000
        price_range = hi - lo
        add("m1__body_bps", body, valid)
        add("m1__upper_wick_fraction", _divide(hi - np.maximum(op, close), price_range), valid)
        add("m1__lower_wick_fraction", _divide(np.minimum(op, close) - lo, price_range), valid)
        add("m1__close_position", _divide(close - lo, price_range), valid)
        for key in ("high", "low"):
            fraction = (values[key + "_ts_ms"] - (self.ends - MINUTE)) / MINUTE
            add(f"m1__{key}_elapsed_fraction", fraction, valid & (fraction >= 0) & (fraction <= 1))
        extreme_clocks_valid = np.isfinite(cols["m1__high_elapsed_fraction"]) & np.isfinite(cols["m1__low_elapsed_fraction"])
        add("m1__high_before_low", (values["high_ts_ms"] < values["low_ts_ms"]).astype(float), extreme_clocks_valid)
        steps = np.r_[0.0, np.abs(np.diff(close))]
        signs = np.sign(body)
        reversals = np.r_[0.0, ((signs[1:] != signs[:-1]) & (signs[1:] != 0) & (signs[:-1] != 0)).astype(float)]
        for window in WINDOWS:
            starts = np.maximum(0, np.arange(n) + 1 - window)
            contiguous = (np.arange(n) + 1 >= window) & (self.ends - self.ends[starts] == (window - 1) * MINUTE)
            covered = contiguous & (_rolling_sum(valid.astype(float), window) == window)
            flow_covered = covered & (_rolling_sum(flow_valid.astype(float), window) == window)
            low = _rolling_extreme(lo, window, False)
            high = _rolling_extreme(hi, window, True)
            ret = (close / op[starts] - 1) * 10_000
            buy, sell = (_rolling_sum(values[key], window) for key in ("buy_notional", "sell_notional"))
            trades = _rolling_sum(values["trade_count"], window)
            turnover = _rolling_sum(values["turnover"], window)
            buy_count = _rolling_sum(values["buy_count"], window)
            sell_count = _rolling_sum(values["sell_count"], window)
            flow = _divide(buy - sell, buy + sell)
            path = _rolling_sum(steps, window) - steps[starts] + np.abs(close[starts] - op[starts])
            prefix = f"w{window}m__"
            add(prefix + "observed", covered.astype(float))
            add(prefix + "flow_observed", flow_covered.astype(float))
            add(prefix + "return_bps", ret, covered)
            add(prefix + "range_bps", (high / low - 1) * 10_000, covered)
            add(prefix + "position", _divide(close - low, high - low), covered)
            add(prefix + "body_rms_bps", np.sqrt(_rolling_sum(body * body, window) / window), covered)
            add(prefix + "path_efficiency", _divide(close - op[starts], path), covered)
            add(prefix + "body_reversals", _rolling_sum(reversals, window) - reversals[starts], covered)
            add(prefix + "buy_notional_log", np.log1p(buy), flow_covered)
            add(prefix + "sell_notional_log", np.log1p(sell), flow_covered)
            add(prefix + "quantity_log", np.log1p(_rolling_sum(values["quantity"], window)), flow_covered)
            add(prefix + "trade_count_log", np.log1p(trades), flow_covered)
            add(prefix + "turnover_log", np.log1p(turnover), flow_covered)
            add(prefix + "flow_imbalance", flow, flow_covered)
            add(prefix + "count_imbalance", _divide(buy_count - sell_count, buy_count + sell_count), flow_covered)
            add(prefix + "max_trade_share", _divide(_rolling_extreme(values["max_trade_notional"], window, True), turnover), flow_covered)
            add(prefix + "flow_price_alignment_bps", flow * ret, flow_covered)
        cols.update(self._hour_features(valid, values))
        minute_of_day = (self.ends // MINUTE) % (24 * 60)
        day_of_week = ((self.ends // (24 * HOUR)) + 3) % 7
        for name, phase in (("utc_day", minute_of_day / (24 * 60)), ("utc_week", day_of_week / 7)):
            add(name + "_sin", np.sin(2 * np.pi * phase))
            add(name + "_cos", np.cos(2 * np.pi * phase))
        cols.update(self._aux_features(self.ends, np.where(valid, close, np.nan)))
        self.names = list(cols)
        if len(self.names) > 200:
            raise AssertionError("feature budget exceeded")
        self.features = np.column_stack(list(cols.values())).astype(np.float32)
        self.features[~np.isfinite(self.features)] = np.nan

    def _hour_features(self, valid: np.ndarray, values: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        hour_rows = []
        for start in np.unique((self.ends - MINUTE) // HOUR * HOUR):
            a = int(np.searchsorted(self.ends, start + MINUTE))
            b = int(np.searchsorted(self.ends, start + HOUR, side="right"))
            if b - a != 60 or not np.all(valid[a:b]) or not np.array_equal(self.ends[a:b], start + np.arange(1, 61) * MINUTE):
                continue
            hour_rows.append((start + HOUR, values["open"][a], np.max(values["high"][a:b]),
                              np.min(values["low"][a:b]), values["close"][b - 1]))
        keys = ("observed", "source_age_s", "return_bps", "range_bps", "position", "upper_wick_fraction",
                "lower_wick_fraction", "atr_14h_frac", "return_3h_bps", "return_6h_bps", "context_14h_observed")
        result = {"h1__" + key: np.full(len(self.ends), np.nan) for key in keys}
        result["h1__observed"][:] = 0.0
        result["h1__context_14h_observed"][:] = 0.0
        if not hour_rows:
            return result
        hours = np.asarray(hour_rows, dtype=np.float64)
        indices = np.searchsorted(hours[:, 0], self.ends, side="right") - 1
        for i in np.unique(indices[indices >= 0]):
            end, op, high, low, close = hours[i]
            mask = indices == i
            age = (self.ends[mask] - end) / 1000
            fresh = age <= 2 * HOUR / 1000
            positions = np.flatnonzero(mask)[fresh]
            if not len(positions):
                continue
            result["h1__observed"][positions] = 1.0
            result["h1__source_age_s"][mask] = age
            base = {"return_bps": (close / op - 1) * 10_000, "range_bps": (high / low - 1) * 10_000,
                    "position": (close - low) / (high - low) if high != low else np.nan,
                    "upper_wick_fraction": (high - max(op, close)) / (high - low) if high != low else np.nan,
                    "lower_wick_fraction": (min(op, close) - low) / (high - low) if high != low else np.nan}
            for key, value in base.items():
                result["h1__" + key][positions] = value
            for window in (3, 6, 14):
                a = i + 1 - window
                if a < 0 or hours[i, 0] - hours[a, 0] != (window - 1) * HOUR:
                    continue
                if window == 14:
                    result["h1__atr_14h_frac"][positions] = np.mean((hours[a:i + 1, 2] - hours[a:i + 1, 3]) / hours[a:i + 1, 4])
                    result["h1__context_14h_observed"][positions] = 1.0
                else:
                    result[f"h1__return_{window}h_bps"][positions] = (close / hours[a, 1] - 1) * 10_000
        return result

    def _aux_features(self, times: np.ndarray, prices: np.ndarray) -> dict[str, np.ndarray]:
        result: dict[str, np.ndarray] = {}
        joined: dict[str, np.ndarray] = {}
        for name, (value_key, duration, max_age) in AUX_SPECS.items():
            channel = self._aux[name]
            count = len(channel["source"])
            indices = np.searchsorted(channel["available"], times, side="right") - 1
            observed = indices >= 0
            safe = np.maximum(indices, 0)
            source_age = np.full(len(times), np.nan)
            available_age = np.full(len(times), np.nan)
            known = np.zeros(len(times))
            if count:
                source_age[observed] = (times[observed] - channel["source"][safe[observed]]) / 1000
                available_age[observed] = (times[observed] - channel["available"][safe[observed]]) / 1000
                known[observed] = channel["received_known"][safe[observed]]
            stale = observed & (source_age * 1000 > max_age)
            usable = observed & ~stale
            prefix = name + "__"
            result[prefix + "observed"] = observed.astype(float)
            result[prefix + "stale"] = stale.astype(float)
            result[prefix + "source_age_s"] = source_age
            result[prefix + "assumed_available_age_s"] = available_age
            result[prefix + "received_clock_known"] = known
            result[prefix + "source_time_only"] = (observed & (known == 0)).astype(float)
            value = np.full(len(times), np.nan)
            if count:
                raw = channel["values"][value_key]
                value[usable] = raw[safe[usable]]
            joined[name] = value
            if name in ("mark", "index"):
                result[prefix + "price_rel"] = value / prices - 1
                for label, first, last in (("bar_return_bps", "open", "close"), ("bar_range_bps", "low", "high")):
                    array = np.full(len(times), np.nan)
                    if count:
                        array[usable] = (channel["values"][last][safe[usable]] / channel["values"][first][safe[usable]] - 1) * 10_000
                    result[prefix + label] = array
            elif name == "oi":
                result[prefix + "log"] = np.log1p(value)
                result[prefix + "notional_log"] = np.log1p(value * prices)
                for lag in (5 * MINUTE, HOUR):
                    change = np.full(len(times), np.nan)
                    if count:
                        target = channel["source"][safe] - lag
                        previous = np.searchsorted(channel["source"], target, side="right") - 1
                        valid = usable & (previous >= 0)
                        prior = np.maximum(previous, 0)
                        # A missing past sample must not masquerade as the named horizon.
                        valid &= channel["source"][prior] == target
                        valid &= channel["available"][prior] <= times
                        change[valid] = value[valid] / raw[prior[valid]] - 1
                    result[prefix + f"change_{lag // MINUTE}m"] = change
            else:
                result[prefix + "rate"] = value
                change = np.full(len(times), np.nan)
                if count:
                    valid = usable & (indices > 0)
                    previous = np.maximum(indices - 1, 0)
                    valid &= channel["source"][safe] - channel["source"][previous] == 8 * HOUR
                    change[valid] = value[valid] - raw[previous[valid]]
                result[prefix + "change"] = change
        result["mark_index__basis_bps"] = (joined["mark"] / joined["index"] - 1) * 10_000
        return result

    def at(self, ts_ms: int) -> dict[str, float]:
        """Features available by this exact timestamp; no forward interpolation."""
        ts_ms = int(ts_ms)
        index = int(np.searchsorted(self.ends, ts_ms, side="right")) - 1
        while index >= 0 and (not self._minute_valid[index] or self._minute_available[index] > ts_ms):
            index -= 1
        if index < 0:
            return {}
        # This branch is needed by in-memory live parity checks. Saved archive
        # bars have no receive clocks and use the precomputed fast path. For
        # real delayed receipts, rebuild only enough causal history for the
        # 14 completed H1 context and the shorter minute windows. Original
        # receipt timestamps remain intact throughout this calculation.
        start = max(0, int(np.searchsorted(self.ends, int(self.ends[index]) - 15 * HOUR)))
        if np.any(self._minute_available[start:index + 1] > self.ends[start:index + 1]):
            replay = type(self).__new__(type(self))
            replay.minutes = self.minutes[start:index + 1]
            replay.ends = self.ends[start:index + 1]
            replay._minute_available = self._minute_available[start:index + 1]
            replay._aux = self._aux
            replay._build(as_of_ms=ts_ms)
            replay._name_index = self._name_index
            return replay._at_row(ts_ms, len(replay.ends) - 1)
        return self._at_row(ts_ms, index)

    def _at_row(self, ts_ms: int, index: int) -> dict[str, float]:
        row = self.features[index].astype(np.float64)
        age = (ts_ms - int(self.ends[index])) / 1000
        if age > 90:
            for i, name in enumerate(self.names):
                if name.startswith(("m1__", "w")):
                    row[i] = 0.0 if name.endswith(("__observed", "__flow_observed")) else np.nan
        row[self._name_index["m1__age_s"]] = age
        result = dict(zip(self.names, row.tolist()))
        close = float(self.minutes[index]["close"]) if age <= 90 else np.nan
        exact = self._aux_features(np.asarray([ts_ms], dtype=np.int64), np.asarray([close]))
        result.update({name: float(values[0]) for name, values in exact.items()})
        h1_age = result.get("h1__source_age_s", np.nan)
        if np.isfinite(h1_age):
            result["h1__source_age_s"] = h1_age + age
            if result["h1__source_age_s"] > 2 * HOUR / 1000:
                for name in self.names:
                    if name.startswith("h1__") and name != "h1__source_age_s":
                        result[name] = 0.0 if name.endswith("observed") else np.nan
        return result

    def source_clocks(self, ts_ms: int) -> dict[str, dict[str, Any]]:
        """Exact source clocks and receipt uncertainty, outside model dimensions."""
        ts_ms = int(ts_ms)
        result = {}
        i = int(np.searchsorted(self.ends, ts_ms, side="right")) - 1
        while i >= 0 and (not self._minute_valid[i] or self._minute_available[i] > ts_ms):
            i -= 1
        if i >= 0:
            result["minutes"] = {
                "source_start_ms": int(self.ends[i]) - MINUTE, "source_end_ms": int(self.ends[i]),
                "assumed_available_at_ms": int(self._minute_available[i]),
                "received_ts_ms": self.minutes[i].get("received_ts_ms"),
                "historical_receipt_unknown": self.minutes[i].get("received_ts_ms") is None,
                "stale": ts_ms - int(self.ends[i]) > 90_000,
            }
        for name, channel in self._aux.items():
            i = int(np.searchsorted(channel["available"], ts_ms, side="right")) - 1
            if i < 0:
                result[name] = {"source_ts_ms": None, "received_ts_ms": None, "observed": False}
                continue
            _, duration, max_age = AUX_SPECS[name]
            result[name] = {
                "source_ts_ms": int(channel["source"][i]),
                "source_end_ms": int(channel["source"][i]) + duration,
                "assumed_available_at_ms": int(channel["available"][i]),
                "received_ts_ms": channel["received"][i], "observed": True,
                "historical_receipt_unknown": channel["received"][i] is None,
                "stale": ts_ms - int(channel["source"][i]) > max_age,
            }
        return result

    def _coverage(self) -> dict[str, Any]:
        slots = (int(self.ends[-1]) - int(self.ends[0])) // MINUTE + 1
        channels = {}
        for name, channel in self._aux.items():
            source = channel["source"]
            observed = self.features[:, self.names.index(name + "__observed")]
            stale = self.features[:, self.names.index(name + "__stale")]
            channels[name] = {
                "rows": len(source), "first_source_ms": int(source[0]) if len(source) else None,
                "last_source_ms": int(source[-1]) if len(source) else None,
                "historical_receipt_unknown_rows": sum(value is None for value in channel["received"]),
                "matrix_observed_rows": int(np.sum(observed)), "matrix_stale_rows": int(np.sum(stale)),
                "max_source_age_ms": AUX_SPECS[name][2],
            }
        return {
            "schema_version": SCHEMA_VERSION, "source_hashes": self.source_hashes,
            "retained_minute_rows": len(self.minutes), "expected_minute_slots": slots,
            "missing_minute_slots": slots - len(self.minutes),
            "first_minute_start_ms": int(self.ends[0]) - MINUTE, "last_minute_end_ms": int(self.ends[-1]),
            "valid_minute_rows": int(np.sum(self._minute_valid)),
            "observed_flow_rows": int(np.sum(self.features[:, self.names.index("m1__flow_observed")])),
            "feature_matrix": {"rows": len(self.ends), "columns": len(self.names), "dtype": "float32", "bytes": self.features.nbytes},
            "windows_minutes": list(WINDOWS), "auxiliary_channels": channels,
            "time_assumptions": {
                "minutes": "completed trade bars assumed finalized at bar_end_ms; missing historical receive clocks are unknown",
                "mark_index": "source ts_ms is bar start; available only at source+60,000+1,000ms",
                "oi_funding": "available only at source ts_ms+1,000ms",
                "historical_receipt_latency": "unknown; the one-second auxiliary lag is an explicit replay assumption, not a measured receipt clock",
                "known_receipts": "when present, availability is no earlier than the recorded receipt",
                "h1": "only complete contiguous UTC hours made from completed retained minutes; missing minutes invalidate their hour",
                "missing": "NaN measurements and separate observed/stale/source_time_only/received_clock_known flags; never backward fill",
            },
            "used_numeric_sources": ["trade OHLC", "total quantity/volume (aliases)", "turnover", "buy/sell notional and count",
                                     "trade count", "maximum trade notional", "high/low source timestamps", "mark/index OHLC", "OI", "funding"],
            "not_retained_or_not_reconstructed": ["L50/order-book history", "liquidations", "separate buy/sell quantity", "exchange receive clocks", "intra-minute paths"],
            "excluded_sources": ["candidate_snapshots_enriched", "all old candidate snapshots", "teacher labels", "future bars"],
            "all_fitted_preprocessing": "none; deterministic causal rolling summaries only",
        }
