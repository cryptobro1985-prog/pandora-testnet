from __future__ import annotations
import csv,gzip,hashlib,json,math,time,urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Tuple

ARCHIVE_ROOT = "https://public.bybit.com/trading"
DEFAULT_SYMBOLS = ("ZEC", "HYPE", "NEAR", "SOL", "ENA", "1000PEPE", "DOGE", "SUI", "AAVE", "WLD")
START_EQUITY = 500.0
FEE_BPS = 4.5
SLIPPAGE_BPS = 2.0
SPLIT_DATE = "2026-10-27"
SEED = 20261104

def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def daterange(start: datetime, end: datetime):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)

def safe_float(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def download(url: str, path: Path, attempts: int = 5) -> Tuple[int, str]:
    part = path.with_suffix(path.suffix + ".partial")
    for attempt in range(attempts):
        h = hashlib.sha256()
        n = 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pandora-universal-research/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r, part.open("wb") as f:
                while True:
                    b = r.read(1024 * 1024)
                    if not b:
                        break
                    n += len(b)
                    h.update(b)
                    f.write(b)
            with gzip.open(part, "rb") as g:
                while g.read(1024 * 1024):
                    pass
            part.replace(path)
            return n, h.hexdigest()
        except Exception:
            part.unlink(missing_ok=True)
            if attempt + 1 >= attempts:
                raise
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError("download retries exhausted")

AGG_HEADER = [
    "ts", "open", "high", "low", "close",
    "buy_notional", "sell_notional", "buy_qty", "sell_qty",
    "buy_count", "sell_count", "max_trade_notional", "trade_count"
]

def aggregate_symbol(symbol: str, start: datetime, end: datetime, out_dir: Path, cache_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}_minutes.csv.gz"
    cov = {"symbol": symbol, "start": start.date().isoformat(), "end_exclusive": end.date().isoformat(), "days": [], "minutes": 0, "trades": 0}
    last_global_ts = None
    with gzip.open(out_path, "wt", newline="") as out:
        w = csv.DictWriter(out, fieldnames=AGG_HEADER)
        w.writeheader()
        for day in daterange(start, end):
            name = f"{symbol}USDT{day:%Y-%m-%d}.csv.gz"
            url = f"{ARCHIVE_ROOT}/{symbol}USDT/{name}"
            raw = cache_dir / name
            day_meta = {"date": day.date().isoformat(), "url": url, "status": "ok", "bytes": 0, "sha256": None, "rows": 0, "minutes": 0}
            try:
                size, sha = download(url, raw)
                day_meta["bytes"] = size
                day_meta["sha256"] = sha
                cur_min = None
                a = None
                prev_ts = None

                def flush():
                    nonlocal a
                    if a is None:
                        return
                    w.writerow(a)
                    day_meta["minutes"] += 1
                    cov["minutes"] += 1
                    a = None

                with gzip.open(raw, "rt", newline="") as f:
                    r = csv.DictReader(f)
                    for i, row in enumerate(r, 2):
                        ts = safe_float(row.get("timestamp"), float("nan"))
                        px = safe_float(row.get("price"), float("nan"))
                        qty = safe_float(row.get("size"), float("nan"))
                        side = row.get("side")
                        market = row.get("symbol") or f"{symbol}USDT"
                        if not (math.isfinite(ts) and math.isfinite(px) and math.isfinite(qty)) or px <= 0 or qty < 0 or side not in ("Buy", "Sell") or market != f"{symbol}USDT":
                            raise ValueError(f"bad archive row {i}")
                        if not (day.timestamp() <= ts < (day + timedelta(days=1)).timestamp()):
                            raise ValueError(f"timestamp outside day at row {i}")
                        if prev_ts is not None and ts < prev_ts:
                            raise ValueError(f"unordered archive at row {i}")
                        if last_global_ts is not None and ts < last_global_ts:
                            raise ValueError("global timestamp order regression")
                        prev_ts = ts
                        last_global_ts = ts
                        minute = int(ts // 60) * 60
                        notional = px * qty
                        if cur_min != minute:
                            flush()
                            cur_min = minute
                            a = {
                                "ts": minute, "open": px, "high": px, "low": px, "close": px,
                                "buy_notional": 0.0, "sell_notional": 0.0,
                                "buy_qty": 0.0, "sell_qty": 0.0,
                                "buy_count": 0, "sell_count": 0,
                                "max_trade_notional": 0.0, "trade_count": 0,
                            }
                        a["high"] = max(float(a["high"]), px)
                        a["low"] = min(float(a["low"]), px)
                        a["close"] = px
                        a["trade_count"] += 1
                        a["max_trade_notional"] = max(float(a["max_trade_notional"]), notional)
                        if side == "Buy":
                            a["buy_notional"] += notional
                            a["buy_qty"] += qty
                            a["buy_count"] += 1
                        else:
                            a["sell_notional"] += notional
                            a["sell_qty"] += qty
                            a["sell_count"] += 1
                        day_meta["rows"] += 1
                        cov["trades"] += 1
                flush()
            except Exception as exc:
                day_meta["status"] = "unavailable_or_invalid"
                day_meta["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
            finally:
                raw.unlink(missing_ok=True)
            cov["days"].append(day_meta)
    cov["days_ok"] = sum(d["status"] == "ok" for d in cov["days"])
    cov["coverage_pct"] = 100.0 * cov["days_ok"] / max(1, len(cov["days"]))
    (out_dir / f"{symbol}_coverage.json").write_text(json.dumps(cov, indent=2))
    return cov
