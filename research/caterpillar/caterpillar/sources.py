"""Public Bybit data sources. TLS/proxy environment is preserved; no credentials required."""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from .model import SYMBOLS, Trade

ARCHIVE_ROOT = "https://public.bybit.com/trading"
REST_ROOT = "https://api.bybit.com"
WS_URL = "wss://stream.bybit.com/v5/public/linear"


class SourceError(RuntimeError):
    pass


def read_url(url, timeout=45, attempts=4):
    """Small JSON responses only. Large archives use streaming download below."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "caterpillar-research/1.0"}), timeout=timeout) as response:
                data = response.read(16*1024*1024+1)
                if len(data) > 16*1024*1024:
                    raise SourceError("JSON response exceeds limit")
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts-1:
                raise SourceError(f"HTTP {exc.code}: {url}") from None
            time.sleep(min(2**attempt, 10))
        except (OSError, ValueError) as exc:
            if attempt == attempts-1:
                raise SourceError(f"{type(exc).__name__} retrieving {url}") from None
            time.sleep(min(2**attempt, 10))


def parse_symbols(value):
    symbols = tuple(x.strip().upper() for x in value.split(","))
    if not symbols or len(symbols) != len(set(symbols)) or not set(symbols) <= set(SYMBOLS):
        raise ValueError("symbols must be a unique subset of: "+",".join(SYMBOLS))
    return symbols


def utc_date(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def archive_row(symbol, row, line):
    try:
        # Official linear public archive: timestamp seconds, side Buy/Sell, size in base units.
        side = {"Buy": 1, "Sell": -1}[row["side"]]
        market = row.get("symbol", symbol+"USDT")
        if market != symbol+"USDT":
            raise ValueError("unexpected symbol")
        trade = Trade(symbol, float(row["timestamp"]), float(row["price"]), float(row["size"]), side, str(row["trdMatchID"]))
        if not trade.valid():
            raise ValueError("invalid numeric or ID fields")
        return trade
    except (KeyError, ValueError, TypeError):
        raise SourceError(f"Invalid archive schema/row at line {line} for {symbol}") from None


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_gzip(path):
    # Read through EOF before research so truncated files/CRC errors cannot silently supply trades.
    with gzip.open(path, "rb") as handle:
        for _ in iter(lambda: handle.read(1024*1024), b""):
            pass


class Archives:
    def __init__(self, cache, max_bytes=8*1024**3):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    def obtain(self, symbol, day):
        name = f"{symbol}USDT{day:%Y-%m-%d}.csv.gz"
        url = f"{ARCHIVE_ROOT}/{symbol}USDT/{name}"
        path = self.cache/name
        manifest = self.cache/(name+".json")
        if path.exists() and manifest.exists():
            try:
                meta = json.loads(manifest.read_text())
                if isinstance(meta, dict) and meta.get("url") == url and meta.get("sha256") == file_sha(path):
                    verify_gzip(path)
                    return path, meta
            except (OSError, EOFError, ValueError) as exc:
                raise SourceError(f"Invalid cached archive/manifest ({type(exc).__name__}): {name}") from None
            raise SourceError("Cached archive checksum/URL mismatch: "+name)
        if path.exists():
            raise SourceError("Unmanifested cache file; preserve it and use an empty cache directory: "+name)
        partial = path.with_suffix(".partial")
        for attempt in range(4):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "caterpillar-research/1.0"})
                with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as handle:
                    size = 0
                    for chunk in iter(lambda: response.read(1024*1024), b""):
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise SourceError("Archive exceeds configured disk-download limit")
                        handle.write(chunk)
                verify_gzip(partial)
                with gzip.open(partial, "rt", newline="") as handle:
                    row = next(csv.DictReader(handle), None)
                    if row is None:
                        raise SourceError("Empty archive")
                    archive_row(symbol, row, 2)
                meta = {"url": url, "sha256": file_sha(partial), "bytes": size,
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                        "verification": "HTTPS and gzip CRC; SHA-256 records local reproducibility, not an independent publisher signature"}
                partial.replace(path)
                manifest.write_text(json.dumps(meta, indent=2)+"\n")
                return path, meta
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise SourceError(f"Archive HTTP {exc.code}: {url}") from None
            except (OSError, EOFError) as exc:
                if attempt == 3:
                    raise SourceError(f"Archive {type(exc).__name__}: {url}") from None
            finally:
                partial.unlink(missing_ok=True)
            time.sleep(min(2**attempt, 10))
        raise SourceError("Archive download exhausted retries")

    def trades(self, symbol, day):
        path, meta = self.obtain(symbol, day)
        def iterate():
            previous = None
            try:
                with gzip.open(path, "rt", newline="") as handle:
                    for line, row in enumerate(csv.DictReader(handle), 2):
                        t = archive_row(symbol, row, line)
                        if previous is not None and t.ts < previous:
                            raise SourceError(f"Unordered archive at line {line}: {path.name}")
                        if not day.timestamp() <= t.ts < (day+timedelta(days=1)).timestamp():
                            raise SourceError(f"Archive timestamp outside requested UTC day: {path.name}")
                        previous = t.ts
                        yield t
            except (OSError, EOFError, UnicodeError, csv.Error) as exc:
                raise SourceError(f"Unreadable archive ({type(exc).__name__}): {path.name}") from None
            if previous is None:
                raise SourceError("Empty archive: "+path.name)
        # A bad row near EOF must not first generate an apparent day's profitable trades.
        # Full schema/order validation costs one streaming pass, not a day-sized array.
        for _ in iterate():
            pass
        return iterate(), meta


def candles(symbol, start, end, interval=1, request_timeout=45, request_attempts=4):
    if symbol not in SYMBOLS or type(interval) is not int or interval <= 0:
        raise ValueError("Invalid OHLCV symbol/interval")
    cursor = int(start.timestamp()*1000)
    end_ms = int(end.timestamp()*1000)
    duration = interval*60*1000
    while cursor < end_ms:
        query = urllib.parse.urlencode({"category": "linear", "symbol": symbol+"USDT", "interval": interval,
                                        "start": cursor, "end": min(end_ms-1, cursor+1000*duration-1), "limit": 1000})
        data = read_url(REST_ROOT+"/v5/market/kline?"+query, timeout=request_timeout, attempts=request_attempts)
        if not isinstance(data, dict):
            raise SourceError("Invalid OHLCV response object")
        if data.get("retCode") != 0:
            raise SourceError("Bybit kline API retCode="+str(data.get("retCode")))
        try:
            rows = sorted(data.get("result", {}).get("list", []), key=lambda row: int(row[0]))
        except (TypeError, ValueError, IndexError, AttributeError):
            raise SourceError("Invalid OHLCV response schema") from None
        if not rows:
            raise SourceError(f"No OHLCV at UTC cursor {cursor} for {symbol}")
        advanced = False
        for row in rows:
            try:
                if not isinstance(row, list) or len(row) != 7:
                    raise ValueError("row length")
                opened = int(row[0])
                values = [float(x) for x in row[1:7]]
            except (TypeError, ValueError):
                raise SourceError("Invalid OHLCV row schema") from None
            if opened < cursor or opened >= end_ms:
                continue
            # A missing interval is missing coverage, not a contiguous observation.
            expected = ((cursor+duration-1)//duration)*duration
            if opened != expected:
                raise SourceError(f"OHLCV coverage gap at UTC cursor {cursor} for {symbol}")
            closed = opened+duration
            if closed <= end_ms and closed <= int(time.time()*1000):
                if not all(math_is_finite_nonnegative(x) for x in values) or min(values[:4]) <= 0:
                    raise SourceError("Invalid OHLCV numeric values")
                if not values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]:
                    raise SourceError("Invalid OHLC ordering")
                yield {"open_ts": opened/1000, "available_ts": closed/1000, "open": values[0], "high": values[1],
                       "low": values[2], "close": values[3], "volume": values[4], "turnover": values[5],
                       "interval_minutes": interval}
            cursor = closed
            advanced = True
        if not advanced:
            raise SourceError("OHLCV pagination did not advance")
        time.sleep(.12)


def math_is_finite_nonnegative(x):
    import math
    return math.isfinite(x) and x >= 0


def closed_h1(symbol, as_of, hours=24):
    """Fetch only already CLOSED hourly structure. Never supplies aggressor flow."""
    if not math.isfinite(as_of) or as_of <= 0 or type(hours) is not int or not 1 <= hours <= 240:
        raise ValueError("Invalid H1 bootstrap boundary/count")
    closed_boundary = int(as_of//3600)*3600
    start = datetime.fromtimestamp(closed_boundary-hours*3600, timezone.utc)
    end = datetime.fromtimestamp(closed_boundary, timezone.utc)
    rows = list(candles(symbol, start, end, interval=60, request_timeout=10, request_attempts=2))
    expected = [start.timestamp()+i*3600 for i in range(hours)]
    if (len(rows) != hours or [r["open_ts"] for r in rows] != expected
            or any(r["available_ts"] != r["open_ts"]+3600 or r["available_ts"] > as_of for r in rows)):
        raise SourceError("Incomplete or unclosed H1 bootstrap for "+symbol)
    return rows


def bootstrap_h1(engine, as_of, hours=24):
    """Bounded parallel public REST requests; deterministic engine mutation after validation."""
    symbols = tuple(engine.states)
    complete = True
    with ThreadPoolExecutor(max_workers=min(4, len(symbols))) as pool:
        futures = {symbol: pool.submit(closed_h1, symbol, as_of, hours) for symbol in symbols}
        for symbol in symbols:
            coverage = {"symbol": symbol, "source": "bybit_rest_closed_h1", "as_of": as_of,
                        "hours_requested": hours, "flow_available": False}
            try:
                rows = futures[symbol].result()
                for candle in rows:
                    engine.seed_h1(symbol, candle, as_of=as_of)
                coverage.update(status="observed", hours_seeded=len(rows),
                                first_open_ts=rows[0]["open_ts"], last_available_ts=rows[-1]["available_ts"])
            except (SourceError, ValueError, OSError) as exc:
                complete = False
                coverage.update(status="unavailable", reason=type(exc).__name__)
                engine.quality(symbol, as_of, "h1_bootstrap_unavailable", failure_type=type(exc).__name__)
            engine.coverage.append(coverage)
    return complete


def historical(engine, cache, start, end, allow_ohlcv=False, resume=False):
    """Process one symbol/day at a time with resumable, causal progress.

    A checkpoint contains engine state plus stream offsets. If a process dies
    mid-day, resume truncates append-only evidence to the last checkpoint and
    skips archive rows older than the restored per-symbol last timestamp.
    """
    if start >= end or end > datetime.now(timezone.utc):
        raise ValueError("Require start < end <= now")
    source = Archives(cache)
    output_root = getattr(engine.output, "root", None)
    progress_path = output_root/"historical_progress.json" if output_root is not None else None
    expected = {"start": start.isoformat(), "end": end.isoformat(),
                "symbols": list(engine.states)}
    if resume and progress_path is None:
        raise ValueError("Resume requires an output root with persistent checkpoints")
    if resume:
        checkpoint_progress = getattr(engine, "resume_extra", {}).get("historical_progress")
        if checkpoint_progress is not None:
            progress = checkpoint_progress
        elif progress_path.is_file():
            progress = json.loads(progress_path.read_text())
        else:
            progress = {**expected, "segments": {}}
        if any(progress.get(k) != v for k, v in expected.items()):
            raise ValueError("Historical progress does not match requested period/symbols")
    else:
        progress = {**expected, "segments": {}}
    completed = progress.setdefault("segments", {})
    incomplete = any(row.get("status") != "observed" for row in completed.values())
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        day_end = min(day+timedelta(days=1), end)
        for symbol in engine.states:
            key = symbol+":"+day.date().isoformat()
            if key in completed:
                continue
            state = engine.states[symbol]
            resume_ts = state.last_ts if resume and state.last_ts is not None and day.timestamp() <= state.last_ts < (day+timedelta(days=1)).timestamp() else None
            coverage = {"symbol": symbol, "start": max(day, start).isoformat(),
                        "end": day_end.isoformat(), "source": "executed_trades",
                        "accepted": 0, "resume_after_ts": resume_ts}
            try:
                iterator, meta = source.trades(symbol, day)
                coverage["archive"] = meta
                seen = skipped = 0
                for t in iterator:
                    if not start.timestamp() <= t.ts < end.timestamp():
                        continue
                    seen += 1
                    if resume_ts is not None:
                        if t.ts < resume_ts:
                            skipped += 1
                            continue
                        if t.ts == resume_ts and t.trade_id in state.ids:
                            skipped += 1
                            continue
                    coverage["accepted"] += int(engine.on_trade(t))
                coverage["rows_in_range"] = seen
                coverage["resume_skipped_rows"] = skipped
                coverage["rejected"] = seen-skipped-coverage["accepted"]
                if not coverage["accepted"] and resume_ts is None:
                    raise SourceError("No accepted trades in requested day/subrange")
                coverage["status"] = "observed"
            except SourceError as exc:
                incomplete = True
                coverage.update(status="unavailable_or_partial", reason=str(exc))
                gap_ts = max(max(day, start).timestamp(), engine.states[symbol].last_ts or 0)
                engine.gap(symbol, gap_ts, "archive_unavailable_or_partial")
                if allow_ohlcv:
                    count = 0
                    try:
                        for candle in candles(symbol, max(day, start), day_end, interval=60):
                            engine.seed_h1(symbol, candle, as_of=candle["available_ts"])
                            engine.on_candle(symbol, candle)
                            count += 1
                        coverage["ohlcv_fallback"] = {
                            "bars": count, "interval_minutes": 60,
                            "flow_available": False}
                    except SourceError as fallback_exc:
                        coverage["ohlcv_error"] = str(fallback_exc)
            engine.coverage.append(coverage)
            completed[key] = {
                "status": coverage["status"],
                "accepted": coverage["accepted"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            if hasattr(engine, "resume_extra"):
                engine.resume_extra["historical_progress"] = progress
            engine.output.flush()
            # The checkpoint is the authoritative commit point. Save its state
            # and stream offsets before publishing the human-readable progress
            # file, so a crash can never skip evidence that was not checkpointed.
            if hasattr(engine, "checkpoint"):
                engine.checkpoint("historical_segment", extra=getattr(engine, "resume_extra", {}))
            if progress_path is not None and hasattr(engine.output, "save_json"):
                engine.output.save_json("historical_progress.json", progress)
            if hasattr(engine, "maybe_status"):
                engine.maybe_status("historical_progress")
            print(f"{symbol} {day:%Y-%m-%d}: {coverage['status']}; accepted={coverage['accepted']}", flush=True)
        day += timedelta(days=1)
    return "incomplete_coverage" if incomplete else "completed"


def replay(engine, path):
    """Normalized trade/GAP JSONL; preserves file order and fails on malformed data."""
    with Path(path).open() as handle:
        for line, raw in enumerate(handle, 1):
            try:
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError("expected object")
                if row.get("event") == "GAP":
                    ts = float(row["ts"])
                    if (row["symbol"] not in engine.states or not math.isfinite(ts) or ts <= 0
                            or not isinstance(row["reason"], str) or not row["reason"]):
                        raise ValueError("invalid gap")
                    engine.gap(row["symbol"], ts, row["reason"])
                    continue
                if row.get("event") == "H1_SEED":
                    as_of = float(row["as_of"])
                    if row["symbol"] not in engine.states or not math.isfinite(as_of) or as_of <= 0:
                        raise ValueError("invalid H1 seed boundary")
                    engine.seed_h1(row["symbol"], row["candle"], as_of=as_of)
                    continue
                if "event" in row:
                    raise ValueError("unknown event")
                t = Trade(**row.get("trade", row))
                if not t.valid() or t.symbol not in engine.states:
                    raise ValueError("invalid trade")
            except (KeyError, TypeError, ValueError):
                raise SourceError(f"Malformed replay line {line}") from None
            engine.on_trade(t)
