"""Two frozen, diagnostic-only November 9 cases using saved Bybit frames."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from zipfile import ZipFile

from research.hype_false_local_entry.replay_early_trajectory import file_sha

CASES = {
    "forming_74_2445": (13641587046, "a93e8c3c0c69ba452c9b7dc902a6cf3bc77f68f76eee2394a8e9a7e59c66c21e",
                        1794182314007, 74.2445),
    "provisional_72_391": (13660165739, "9eaf8f0880dd55564db6f4345670610b61fff51f2f7c09489bd65de0b35ac956",
                           1794211320000, 72.391),
}
EVIDENCE_SHA = "56f9a66f921c9daa0b530c8fb2b7069a5778af17ceb0e2cda30d5890f2fca0c4"


def iter_member(archive, name):
    with gzip.open(archive.open(name), "rt", encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def market_records(path, start, stop):
    trades, samples, context = {}, [], []
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("RESILIENT_CAPTURE_MANIFEST.json"))
        for name in archive.namelist():
            if name.endswith("/HYPE_live_raw_frames.jsonl.gz"):
                for r in iter_member(archive, name):
                    recv = int(r["received_ts_ms"])
                    if not start <= recv <= stop:
                        continue
                    event = json.loads(r["raw_text"])
                    if event.get("topic") != "publicTrade.HYPEUSDT":
                        continue
                    for z in event["data"]:
                        if z["S"] in ("Buy", "Sell"):
                            row = (recv, int(z["T"]), float(z["p"]), float(z["v"]), z["S"])
                            old = trades.get(z["i"])
                            if old is None or row[0] < old[0]:
                                trades[z["i"]] = row
            elif name.endswith("/HYPE_live_microstructure_1s.jsonl.gz"):
                samples.extend(r for r in iter_member(archive, name) if start <= r["ts_ms"] <= stop)
            elif name.endswith("/HYPE_structural_context_1m.jsonl.gz"):
                context.extend(r for r in iter_member(archive, name) if start <= r["ts_ms"] <= stop)
    return (sorted(trades.values(), key=lambda x: (x[1], x[0])),
            sorted(samples, key=lambda x: x["ts_ms"]), sorted(context, key=lambda x: x["ts_ms"]),
            manifest)


def window(trades, samples, start, stop):
    rows = [t for t in trades if start < t[1] <= stop and t[0] <= stop]
    books = [r for r in samples if start < r["ts_ms"] <= stop and r.get("book_valid")
             and r.get("spread_bps", 0) > 0 and r.get("mid") is not None]
    buy = sum(p*q for _, _, p, q, side in rows if side == "Buy")
    sell = sum(p*q for _, _, p, q, side in rows if side == "Sell")
    ret = 10_000*(rows[-1][2]/rows[0][2]-1) if rows else None
    tail = books[-1] if books else {}
    return {"unique_trades": len(rows), "buy_notional": buy if rows else None,
            "sell_notional": sell if rows else None,
            "trade_return_bps": ret, "trade_low": min((r[2] for r in rows), default=None),
            "trade_last": rows[-1][2] if rows else None,
            "buy_impact_bps_per_100k": max(0.0, ret)*100_000/buy if buy else None,
            "sell_impact_bps_per_100k": max(0.0, -ret)*100_000/sell if sell else None,
            "valid_instant_book_samples": len(books),
            "sampled_mid_low": min((r["mid"] for r in books), default=None),
            "last_sample_ts_ms": tail.get("ts_ms"),
            "last_book_imbalance_l5": tail.get("book_imbalance_5"),
            "last_book_imbalance_l25": tail.get("book_imbalance_25"),
            "last_oi": tail.get("open_interest"),
            "last_oi_age_ms": stop-tail["oi_ts_ms"] if tail.get("oi_ts_ms") and tail["oi_ts_ms"] <= stop else None}


def compare(path, key, events):
    artifact, digest, event_time, expected = CASES[key]
    if file_sha(path) != digest:
        raise ValueError(f"unexpected case archive checksum: {artifact}")
    trades, samples, context, manifest = market_records(path, event_time-180_000, event_time+660_000)
    matching = [r for r in trades if event_time <= r[1] < event_time+60_000 and r[2] == expected]
    print_ts = matching[0][1] if matching else event_time
    available = max(print_ts, matching[0][0]) if matching else event_time
    evidence = []
    previous = None
    for r in events:
        stamp = r.get("ts_ms", r.get("detected_ts_ms", 0))
        if r.get("side") != "LOW":
            continue
        if r["event"] == "NEW_CANDIDATE" and stamp < available and (
            previous is None or stamp > previous["ts_ms"]
        ):
            previous = {k: r[k] for k in ("candidate_id", "ts_ms", "price")}
        if event_time-90_000 <= stamp <= available+600_000:
            evidence.append({k: r[k] for k in ("event", "ts_ms", "detected_ts_ms", "candidate_id",
                                               "price", "stage", "accepted", "probability") if k in r})
    prior_context = next((r for r in reversed(context) if r["ts_ms"] <= available), {})
    return {"artifact": artifact, "sha256": digest, "run_id": manifest["run_id"],
            "reference_anchor_ms": event_time, "reference_price": expected,
            "matching_tape_prints": len(matching),
            "previous_logged_low": previous,
            "first_tape_print": (dict(exchange_ts_ms=print_ts, receive_ts_ms=matching[0][0],
                                      price=expected) if matching else None),
            "reference_minute": window(trades, samples, event_time//60_000*60_000-1,
                                       event_time//60_000*60_000+59_999),
            "pre_60s": window(trades, samples, available-60_000, available),
            "post": {str(sec): window(trades, samples, available, available+1000*sec)
                     for sec in (60, 180, 300)},
            "post_disjoint": {f"{a}-{b}": window(trades, samples, available+1000*a, available+1000*b)
                              for a, b in ((0, 60), (60, 180), (180, 300))},
            "context_asof": {k: prior_context.get(k) for k in (
                "ts_ms", "rolling_6h_low", "mark_price", "index_price", "funding_rate",
                "open_interest", "long_short_holder_ratio")},
            "logged_events": evidence}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--forming", type=Path, required=True)
    p.add_argument("--noon", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if file_sha(args.evidence) != EVIDENCE_SHA:
        p.error("unexpected live events archive checksum")
    with ZipFile(args.evidence) as archive:
        events = list(iter_member(archive, "LOCAL_EVENTS.recent.jsonl.gz"))
    result = {"phase": "post_freeze_live_diagnostic", "real_orders": False,
              "forming_74_2445": compare(args.forming, "forming_74_2445", events),
              "provisional_72_391": compare(args.noon, "provisional_72_391", events),
              "limits": "Instantaneous book samples and received trades. Liquidation absence is not inferred "
                        "from silence. These case windows were excluded from model fitting and selection."}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
