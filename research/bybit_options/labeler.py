"""Causal executable-price option outcome labeler.

Entry uses the first observed ask at/after signal timestamp, exit uses bid.
Missing observations are censored, never filled with future-derived estimates.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

HORIZONS_SECONDS = (60, 180, 300, 900, 1800, 3600, 10800, 21600)

def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None

def rows(path):
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)

def extract_surfaces(path):
    by_symbol = {}
    for snap in rows(path) or ():
        ts = int(snap["ts_ms"])
        underlying = (snap.get("context") or {}).get("ticker") or {}
        spot = number(underlying.get("lastPrice"))
        for opt in snap.get("tickers", []):
            symbol = opt.get("symbol")
            if not symbol:
                continue
            bid = number(opt.get("bid1Price"))
            ask = number(opt.get("ask1Price"))
            mark = number(opt.get("markPrice"))
            iv = number(opt.get("markIv"))
            underlying_price = number(opt.get("underlyingPrice")) or spot
            if bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask:
                continue
            by_symbol.setdefault(symbol, []).append({
                "ts_ms": ts, "bid": bid, "ask": ask, "mark": mark,
                "iv": iv, "underlying": underlying_price
            })
    for points in by_symbol.values():
        points.sort(key=lambda x:x["ts_ms"])
    return by_symbol

def label_signal(signal, points, max_entry_lag_ms=120000, max_exit_lag_ms=120000):
    ts = int(signal["ts_ms"])
    expiry = int(signal.get("expiry_ms") or 0)
    # The signal must precede all observations used to establish the outcome.
    entry = next((p for p in points if ts <= p["ts_ms"] <= ts + max_entry_lag_ms), None)
    base = {
        "signal_ts_ms":ts, "symbol":signal["symbol"],
        "score":signal.get("score"), "action":signal.get("action"),
        "entry_status":"observed" if entry else "censored_no_fresh_ask",
        "outcomes":{}
    }
    if not entry:
        return base
    premium = entry["ask"]
    base["entry"] = entry
    base["max_loss_premium_units"] = premium
    horizons = [(f"{h}s", ts + h * 1000) for h in HORIZONS_SECONDS]
    if expiry:
        horizons.append(("expiry", expiry))
    for key, target in horizons:
        if expiry and target > expiry:
            base["outcomes"][key] = {"status":"censored_after_expiry"}
            continue
        # Expiry requires a verified settlement observation; an ordinary bid
        # after expiry is not a valid executable sale.
        if key == "expiry":
            base["outcomes"][key] = {"status":"censored_no_verified_settlement",
                "reason":"expiry cannot be priced from post-expiry bid/mark"}
            continue
        exit_pt = next((p for p in points if target <= p["ts_ms"] <= target+max_exit_lag_ms and (not expiry or p["ts_ms"] < expiry)),None)
        path = [p for p in points if entry["ts_ms"] <= p["ts_ms"] <= target and (not expiry or p["ts_ms"] <= expiry)]
        if not exit_pt:
            base["outcomes"][key] = {"status":"censored_no_fresh_bid","observations":len(path)}
            continue
        if not path:
            base["outcomes"][key] = {"status":"censored_no_path"}
            continue
        best = max(path,key=lambda p:p["bid"])
        worst = min(path,key=lambda p:p["bid"])
        base["outcomes"][key] = {
            "status":"observed",
            "exit_ts_ms":exit_pt["ts_ms"],
            "exit_bid":exit_pt["bid"],
            "exit_mark":exit_pt["mark"],
            "gross_return_pct":100*(exit_pt["bid"]/premium-1),
            "mfe_pct":100*(best["bid"]/premium-1),
            "mae_pct":100*(worst["bid"]/premium-1),
            "time_to_mfe_seconds":(best["ts_ms"]-entry["ts_ms"])/1000,
            "iv_change":None if entry["iv"] is None or exit_pt["iv"] is None else exit_pt["iv"]-entry["iv"],
            "underlying_move_pct":None if not entry["underlying"] or exit_pt["underlying"] is None else 100*(exit_pt["underlying"]/entry["underlying"]-1),
            "round_trip_spread_pct":100*(entry["ask"]-entry["bid"])/premium,
            "fee_adjusted_return_pct":None,
            "fee_status":"not_configured",
            "observations":len(path)
        }
    return base

def run(directory):
    folder=Path(directory)
    surfaces=extract_surfaces(folder/"surfaces.jsonl.gz")
    signals=list(rows(folder/"signals.jsonl.gz") or [])
    output=folder/"labels.jsonl.gz"
    observed=censored=0
    with gzip.open(output,"wt",encoding="utf-8") as dest:
        for sig in signals:
            result=label_signal(sig,surfaces.get(sig["symbol"],[]))
            for value in result["outcomes"].values():
                if value["status"]=="observed": observed+=1
                else: censored+=1
            dest.write(json.dumps(result,sort_keys=True)+"\n")
    manifest=json.loads((folder/"RUN_MANIFEST.json").read_text())
    cfg=json.dumps(manifest.get("config",{}),sort_keys=True).encode()
    report={"signal_count":len(signals),"observed_horizons":observed,"censored_horizons":censored,
        "config_sha256":hashlib.sha256(cfg).hexdigest(),
        "feature_schema":"bybit-options-gamma-v0.1",
        "cutoff_ms":max((int(x["ts_ms"]) for x in signals),default=None),
        "model_status":"untrained","edge_proven":False,
        "rejected_hypotheses":[],
        "limitations":["Fees/slippage beyond observed spread not configured","Sparse surfaces censor short horizons","No independent forward evaluation yet","Expiry settlement is censored until verified exchange settlement records are collected","L25 depth and size-aware execution are not available in this labeler"]}
    (folder/"LABEL_REPORT.json").write_text(json.dumps(report,indent=2))
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("directory")
    args=p.parse_args()
    print(json.dumps(run(args.directory),indent=2))
