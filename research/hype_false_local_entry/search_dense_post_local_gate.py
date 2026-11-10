"""Search a causal post-Local veto on dense first-flip streams.

Discovery thresholds are selected on one strict period and scored unchanged on
another. Teacher labels are used only by the offline scorer, never to compute
signal features. Research/paper only; no order execution.
"""
import argparse
import gzip
import json
from bisect import bisect_left
from pathlib import Path
from statistics import median

from .audit_dense_coverage import read_jsonl
from .causal_sequential_engine import CausalReversalMachine
from .first_flip_path_audit import score_first_flips


def bar_end(b):
    if b.get("bar_end_ms") is not None:
        return int(b["bar_end_ms"])
    if b.get("start_ms") is not None:
        return int(b["start_ms"]) + int(b.get("interval_ms", 60000))
    return int(b["ts_ms"])


def load_period(base):
    base = Path(base)
    with gzip.open(base / "labels.json.gz", "rt", encoding="utf-8") as f:
        doc = json.load(f)
    labels = sorted(
        (x for x in doc.get("strict", []) if x.get("reference_finalized")),
        key=lambda x: int(x["extreme_interval_start_ms"]),
    )
    bars = sorted(list(read_jsonl(base / "compact_1m.jsonl.gz")), key=bar_end)
    m = CausalReversalMachine()
    emitted = []
    for b in bars:
        emitted.extend(m.on_bar(b))
    flips = [s for s in emitted if s.core_flip and s.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")]
    return bars, labels, flips


def num(b, key):
    try:
        v = float(b.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return v


def side_features(bars, idx, signal):
    side = signal.side
    sign = 1.0 if side == "LOW" else -1.0
    close = float(bars[idx]["close"])
    out = {
        "score": float(signal.score),
        "retrace_bps": sign * (close / float(signal.extreme_price) - 1.0) * 10000.0,
    }

    def window(n):
        lo = max(0, idx - n + 1)
        return bars[lo:idx + 1]

    def close_before(n):
        j = max(0, idx - n)
        return float(bars[j]["close"])

    for n in (3, 5, 10):
        w = window(n)
        prev = close_before(n)
        move = sign * (close / prev - 1.0) * 10000.0 if prev > 0 else 0.0
        buy = sum(num(x, "buy_notional") for x in w)
        sell = sum(num(x, "sell_notional") for x in w)
        total = buy + sell
        new_notional = buy if side == "LOW" else sell
        flow = sign * (buy - sell) / total if total > 0 else 0.0
        steps = []
        fav = 0
        seq = [float(x["close"]) for x in bars[max(0, idx-n):idx+1]]
        for a, b in zip(seq, seq[1:]):
            r = sign * (b / a - 1.0) * 10000.0 if a > 0 else 0.0
            steps.append(abs(r))
            fav += r > 0
        path = sum(steps)
        out[f"move{n}_bps"] = move
        out[f"flow{n}"] = flow
        out[f"eff_new_{n}"] = max(move, 0.0) / max(new_notional / 100000.0, 1e-9)
        out[f"persist{n}"] = fav / max(1, len(seq)-1)
        out[f"path_eff{n}"] = max(move, 0.0) / max(path, 1e-9)

    # Causal same-leg comparison proxy: current 5m new-side efficiency versus
    # the strongest prior 5m burst in the preceding hour, excluding overlap.
    cur_eff = out["eff_new_5"]
    prior = []
    for j in range(max(5, idx-60), max(5, idx-5)):
        c = float(bars[j]["close"])
        p = float(bars[j-5]["close"])
        mv = sign * (c / p - 1.0) * 10000.0 if p > 0 else 0.0
        w = bars[j-4:j+1]
        buy = sum(num(x, "buy_notional") for x in w)
        sell = sum(num(x, "sell_notional") for x in w)
        new_n = buy if side == "LOW" else sell
        prior.append(max(mv, 0.0) / max(new_n / 100000.0, 1e-9))
    pmax = max(prior) if prior else 0.0
    out["eff5_vs_prior_max"] = cur_eff / max(pmax, 1e-9)
    out["eff5_minus_prior_max"] = cur_eff - pmax

    # Range-normalized rejection, causal at the signal close.
    w60 = bars[max(0, idx-59):idx+1]
    hi = max(float(x["high"]) for x in w60)
    lo = min(float(x["low"]) for x in w60)
    range_bps = (hi / lo - 1.0) * 10000.0 if lo > 0 else 0.0
    out["retrace_over_range60"] = out["retrace_bps"] / max(range_bps, 1e-9)
    return out


def feature_map(bars, flips):
    ends = [bar_end(b) for b in bars]
    out = {}
    for s in flips:
        i = bisect_left(ends, int(s.ts_ms))
        if i >= len(ends) or ends[i] != int(s.ts_ms):
            continue
        out[(int(s.ts_ms), s.side)] = side_features(bars, i, s)
    return out


def percentile(vals, q):
    vals = sorted(vals)
    if not vals:
        return 0.0
    pos = (len(vals)-1) * q
    lo = int(pos)
    hi = min(len(vals)-1, lo+1)
    frac = pos-lo
    return vals[lo]*(1-frac)+vals[hi]*frac


def apply_gate(flips, fmap, gate):
    out = []
    for s in flips:
        f = fmap.get((int(s.ts_ms), s.side))
        if f is None:
            continue
        ok = all(f[name] >= thr for name, thr in gate)
        if ok:
            out.append(s)
    return out


def compact_score(bars, labels, flips):
    s = score_first_flips(bars, labels, flips)
    t = s["completed_swing_true_first"]
    w = s["completed_swing_wrong_first"]
    accepted = t + w
    return {
        "true_first": t,
        "wrong_first": w,
        "accepted_first": accepted,
        "precision": t / accepted if accepted else None,
        "recall": s["completed_swing_recall"],
        "median_lag_ms": s["completed_swing_median_lag_ms"],
        "median_entry_bps": s["completed_swing_median_entry_distance_bps"],
        "median_remaining": s["completed_swing_median_remaining_swing_fraction"],
        "median_adverse_bps": s["completed_swing_median_adverse_extension_bps"],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dev-dir", required=True)
    p.add_argument("--test-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    db, dl, df = load_period(args.dev_dir)
    tb, tl, tf = load_period(args.test_dir)
    dm, tm = feature_map(db, df), feature_map(tb, tf)

    names = [
        "retrace_bps", "move3_bps", "move5_bps", "move10_bps",
        "flow3", "flow5", "flow10", "eff_new_3", "eff_new_5", "eff_new_10",
        "persist3", "persist5", "persist10", "path_eff3", "path_eff5", "path_eff10",
        "eff5_vs_prior_max", "eff5_minus_prior_max", "retrace_over_range60",
    ]
    # Discovery thresholds only. High-side normalized features all use >=.
    thresholds = {}
    for name in names:
        vals = [f[name] for f in dm.values()]
        qs = [0.10,0.20,0.30,0.40,0.50,0.60,0.70,0.80,0.90]
        thresholds[name] = sorted(set(round(percentile(vals,q), 12) for q in qs))

    candidates = []
    # Single-feature gates.
    for a in names:
        for ta in thresholds[a]:
            gate=((a,ta),)
            score=compact_score(db,dl,apply_gate(df,dm,gate))
            if score["wrong_first"] == 0 and score["true_first"] >= 10:
                candidates.append((score["true_first"], -len(gate), gate, score))
    # Two-feature gates: restrict to causal core to limit meta-search.
    core = ["retrace_bps","move3_bps","move5_bps","flow3","flow5",
            "eff_new_3","eff_new_5","persist5","path_eff5",
            "eff5_vs_prior_max","eff5_minus_prior_max","retrace_over_range60"]
    for ia,a in enumerate(core):
        for b in core[ia+1:]:
            for ta in thresholds[a]:
                for tbv in thresholds[b]:
                    gate=((a,ta),(b,tbv))
                    score=compact_score(db,dl,apply_gate(df,dm,gate))
                    if score["wrong_first"] == 0 and score["true_first"] >= 10:
                        candidates.append((score["true_first"], -len(gate), gate, score))

    candidates.sort(key=lambda x:(x[0],x[1]), reverse=True)
    top=[]
    seen=set()
    for _,__,gate,dev_score in candidates:
        key=tuple(gate)
        if key in seen:
            continue
        seen.add(key)
        test_score=compact_score(tb,tl,apply_gate(tf,tm,gate))
        top.append({"gate":[{"feature":a,"min":v} for a,v in gate],
                    "development":dev_score,"test":test_score})
        if len(top)>=25:
            break

    baseline_dev=compact_score(db,dl,df)
    baseline_test=compact_score(tb,tl,tf)
    result={
        "status":"research_only_no_orders",
        "selection":"thresholds selected on dev only; test scored unchanged",
        "dev_dir":str(args.dev_dir),"test_dir":str(args.test_dir),
        "baseline":{"development":baseline_dev,"test":baseline_test},
        "top_dev_zero_wrong_gates":top,
    }
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({
        "baseline":result["baseline"],
        "top5":top[:5],
    },indent=2))


if __name__ == "__main__":
    main()
