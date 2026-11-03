"""Public Bybit data sources. TLS/proxy environment is preserved; no credentials required."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
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
            meta = json.loads(manifest.read_text())
            if meta.get("url") == url and meta.get("sha256") == file_sha(path):
                verify_gzip(path)
                return path, meta
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
            with gzip.open(path, "rt", newline="") as handle:
                for line, row in enumerate(csv.DictReader(handle), 2):
                    t = archive_row(symbol, row, line)
                    if previous is not None and t.ts < previous:
                        raise SourceError(f"Unordered archive at line {line}: {path.name}")
                    if not day.timestamp() <= t.ts < (day+timedelta(days=1)).timestamp():
                        raise SourceError(f"Archive timestamp outside requested UTC day: {path.name}")
                    previous = t.ts
                    yield t
        return iterate(), meta


def candles(symbol, start, end, interval=1):
    cursor = int(start.timestamp()*1000)
    end_ms = int(end.timestamp()*1000)
    duration = interval*60*1000
    while cursor < end_ms:
        query = urllib.parse.urlencode({"category": "linear", "symbol": symbol+"USDT", "interval": interval,
                                        "start": cursor, "end": min(end_ms-1, cursor+1000*duration-1), "limit": 1000})
        data = read_url(REST_ROOT+"/v5/market/kline?"+query)
        if data.get("retCode") != 0:
            raise SourceError("Bybit kline API retCode="+str(data.get("retCode")))
        rows = sorted(data.get("result", {}).get("list", []), key=lambda row: int(row[0]))
        if not rows:
            raise SourceError(f"No OHLCV at UTC cursor {cursor} for {symbol}")
        advanced = False
        for row in rows:
            opened = int(row[0])
            if opened < cursor or opened >= end_ms:
                continue
            closed = opened+duration
            if closed <= end_ms and closed <= int(time.time()*1000):
                values = [float(x) for x in row[1:7]]
                if not all(math_is_finite_nonnegative(x) for x in values) or min(values[:4]) <= 0:
                    raise SourceError("Invalid OHLCV numeric values")
                if not values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]:
                    raise SourceError("Invalid OHLC ordering")
                yield {"open_ts": opened/1000, "available_ts": closed/1000, "open": values[0], "high": values[1],
                       "low": values[2], "close": values[3], "volume": values[4], "turnover": values[5]}
            cursor = closed
            advanced = True
        if not advanced:
            raise SourceError("OHLCV pagination did not advance")
        time.sleep(.12)


def math_is_finite_nonnegative(x):
    import math
    return math.isfinite(x) and x >= 0


def historical(engine, cache, start, end, allow_ohlcv=False):
    """Process one symbol/day at a time, chronological within each independent symbol.

    No shared capital/ranking/cross-symbol decisions; global timestamp merge is unnecessary.
    Memory is bounded independently of the requested date range.
    """
    if start >= end or end > datetime.now(timezone.utc):
        raise ValueError("Require start < end <= now")
    source = Archives(cache)
    incomplete = False
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        day_end = min(day+timedelta(days=1), end)
        for symbol in engine.states:
            coverage = {"symbol": symbol, "start": max(day, start).isoformat(), "end": day_end.isoformat(), "source": "executed_trades", "accepted": 0}
            try:
                iterator, meta = source.trades(symbol, day)
                coverage["archive"] = meta
                seen = 0
                for t in iterator:
                    if start.timestamp() <= t.ts < end.timestamp():
                        seen += 1
                        coverage["accepted"] += int(engine.on_trade(t))
                if not seen:
                    raise SourceError("No trades in requested day/subrange")
                coverage["status"] = "observed"
            except SourceError as exc:
                incomplete = True
                coverage.update(status="unavailable_or_partial", reason=str(exc))
                engine.gap(symbol, max(day, start).timestamp(), "archive_unavailable_or_partial")
                if allow_ohlcv:
                    count = 0
                    try:
                        for candle in candles(symbol, max(day, start), day_end):
                            engine.on_candle(symbol, candle)
                            count += 1
                        coverage["ohlcv_fallback"] = {"bars": count, "flow_available": False}
                    except SourceError as fallback_exc:
                        coverage["ohlcv_error"] = str(fallback_exc)
            engine.coverage.append(coverage)
            engine.output.flush()
            print(f"{symbol} {day:%Y-%m-%d}: {coverage['status']}; accepted={coverage['accepted']}", flush=True)
        day += timedelta(days=1)
    return "incomplete_coverage" if incomplete else "completed"


def replay(engine, path):
    """Normalized trade/GAP JSONL; preserves file order and fails on malformed data."""
    with Path(path).open() as handle:
        for line, raw in enumerate(handle, 1):
            try:
                row = json.loads(raw)
                if row.get("event") == "GAP":
                    engine.gap(row["symbol"], float(row["ts"]), row["reason"])
                    continue
                t = Trade(**row.get("trade", row))
            except (TypeError, ValueError):
                raise SourceError(f"Malformed replay line {line}") from None
            engine.on_trade(t)
