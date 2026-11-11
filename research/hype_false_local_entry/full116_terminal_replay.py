"""Budgeted HYPE L6/K2 terminal research on the verified availability cohorts."""
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from research.hype_false_local_entry import early_trajectory_features as m1
from research.hype_false_local_entry import first_signal_objective as first
from research.hype_false_local_entry import full116_candidate_features as features
from research.hype_false_local_entry import full116_sources as sources
from research.hype_false_local_entry import replay_early_trajectory as prior
from research.hype_false_local_entry.hard_survival_gate import HardCandidate, next_signal
from research.hype_local_only.replay_ultra_survival_v2 import RULES as ULTRA

CAPS = (30, 50, 70, 100, 150)
SCORE_THRESHOLDS = (0.05, 0.10, 0.20, 0.35)
DEV_SCREEN = {"episodes": 8, "true_first": 3, "precision": 0.35,
              "recall": 0.15, "precision_gain": 0.12}
PORTFOLIO = Path(__file__).resolve().parents[1]/"hype_strict_h1_guard"/"FINAL_LOCAL_STRATEGY_PORTFOLIO_2026-11-09.json"
QUALITY_ONLY = {56, 57, 60, 77, 78, 79, 80, 116}


def dump(path, document):
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+"\n",
                    encoding="utf-8")


def signal_scope(tape, labels):
    labs, episodes, eligible = prior.scoring_scope(tape, labels)
    # Some legacy labels did not encode the finalization timestamp explicitly.
    # In that case the next opposite K2 pivot is the earliest certification.
    mature_at = {ep.ep: int(labs[ep.ep].get("reference_finalized_ms")
                            or labs[ep.ep+1]["label_available_ms"]) for ep in episodes}
    deadline = {ep.ep: int(labs[ep.ep+1]["extreme_interval_start_ms"]) for ep in episodes}
    target = {int(label["label_id"]): label for label in labs}
    return (labs, episodes, eligible), mature_at, deadline, target


def outcomes(states, scope):
    """Attach offline labels to decision indices after all X was built."""
    (_, episodes, eligible), _, deadline, targets = scope
    tags = []
    for row in states:
        ep = first.assign_episode(row["candidate_ts_ms"], row["side"], episodes)
        if ep is None or ep.ep not in eligible or row["signal_ts_ms"] >= deadline[ep.ep]:
            tags.append(None)
            continue
        label = targets[ep.target_label_id]
        minute = row["candidate_ts_ms"]//m1.MINUTE*m1.MINUTE
        terminal = minute == label["extreme_interval_start_ms"] and math.isclose(
            row["price"], label["extreme_price"], rel_tol=1e-10, abs_tol=1e-8)
        tags.append((ep.ep, terminal))
    return tags


def summarize(tape, labels, side, states, scope, subset=None, keep_records=False):
    labs, episodes, eligible = scope
    eligible = eligible if subset is None else eligible & subset
    result = prior.evaluate_side(tape, labels, side, states, (labs, episodes, eligible))
    records = result.pop("first_signals")
    remaining = []
    for record in records:
        if record["true_first"]:
            nxt = float(labs[record["episode"]+1]["extreme_price"])
            sign = 1 if side == "LOW" else -1
            distance = max(0.0, sign*(nxt/record["signal_price"]-1)*10_000)
            remaining.append(distance)
            record["remaining_swing_bps"] = distance
    result["remaining_swing_bps"] = prior.distribution(remaining)
    if keep_records:
        result["first_signals"] = records
    return result


def on_band(row, cap):
    return 0 < row["retrace_bps"] <= cap


def matrix(rows, names):
    return np.asarray([[row["features"].get(name, np.nan) for name in names]
                       for row in rows], dtype=float)


def fit_model(rows, tags, points=None):
    names = sorted({name for row in rows for name in row["features"]
                    if features.point_id(name) not in QUALITY_ONLY
                    and (points is None or features.point_id(name) in points)})
    y = np.asarray([terminal for _, terminal in tags], dtype=int)
    if not rows or min(np.bincount(y, minlength=2)) < 3:
        return None
    x = matrix(rows, names)
    observed = np.isfinite(x).sum(axis=0) >= 4
    names = [name for name, keep in zip(names, observed) if keep]
    x = x[:, observed]
    varied = np.nanmax(x, axis=0) > np.nanmin(x, axis=0)
    names = [name for name, keep in zip(names, varied) if keep]
    x = x[:, varied]
    if not names:
        return None
    centers = np.nanmedian(x, axis=0)
    lo, hi = np.nanquantile(x, (0.25, 0.75), axis=0)
    scale = np.where(hi > lo, hi-lo, np.nanstd(x, axis=0))
    missing = np.flatnonzero(np.isnan(x).any(axis=0))
    # Every candidate has the same total weight within an episode regardless
    # of how many checkpoints it survives. Every episode has equal weight.
    repeats = Counter(row["candidate_id"] for row in rows)
    candidates_per_episode = Counter(ep for ep, _ in {
        (tag[0], row["candidate_id"]) for row, tag in zip(rows, tags)
    })
    weights = np.asarray([3.0/(repeats[r["candidate_id"]]*candidates_per_episode[t[0]])
                          for r, t in zip(rows, tags)])
    model = LogisticRegression(C=0.25, solver="lbfgs", max_iter=300)
    model.fit(transform(x, centers, scale, missing), y, sample_weight=weights)
    return {"feature_names": names, "centers": centers.tolist(), "scale": scale.tolist(),
            "missing_indicator_columns": missing.tolist(),
            "coef": model.coef_[0].tolist(), "intercept": float(model.intercept_[0]),
            "fit_rows": len(rows), "fit_episodes": len(candidates_per_episode)}


def transform(x, centers, scale, missing):
    absent = np.isnan(x)
    z = np.clip((x-centers)/scale, -8, 8)
    # The median is a numeric placeholder. Missingness remains explicit.
    return np.column_stack((np.where(absent, 0, z), absent[:, missing]))


def probabilities(rows, model):
    if not rows:
        return np.array([])
    x = matrix(rows, model["feature_names"])
    z = transform(x, model["centers"], model["scale"], model["missing_indicator_columns"])
    logits = z @ np.asarray(model["coef"]) + model["intercept"]
    return 1/(1+np.exp(-np.clip(logits, -60, 60)))


def frontier(points):
    """Keep non-dominated precision, recall, distance and latency trade-offs."""
    qualified = [p for p in points if p["metrics"]["true_first"] >= 3]
    def objectives(point):
        m = point["metrics"]
        return (m["precision"], m["recall"], -m["true_distance_bps"]["p90"],
                -m["true_latency_s"]["p90"])
    values = [objectives(p) for p in qualified]
    return [p for p, a in zip(qualified, values) if not any(
        all(y >= x for x, y in zip(a, b)) and any(y > x for x, y in zip(a, b))
        for b in values)]


def develop(period, kinds):
    tape, labels, states, scope = (period[k] for k in ("tape", "labels", "early", "scope"))
    base, mature, deadlines, _ = scope
    _, episodes, eligible = base
    tags = outcomes(states, scope)
    span = int(tape.end[-1] - tape.start[0])
    cuts = [int(tape.start[0] + span*f) for f in (0.50, 0.75, 1.0)]
    selections, fitted, result = {}, {}, {}
    for side in m1.SIDES:
        result[side], fitted[side] = {}, {}
        for name, points in kinds.items():
            rows = [dict(r, features={**r["features"], **r.get("clean_features", {})})
                    for r in states] if name == "clean_micro" else states
            heldout, seen, brier = [], set(), []
            indices = [i for i, row in enumerate(rows) if row["side"] == side and
                       on_band(row, CAPS[-1]) and
                       (name != "clean_micro" or bool(features.available_points(
                           row.get("clean_features", {})) - QUALITY_ONLY))]
            for begin, end in zip(cuts, cuts[1:]):
                test_episodes = {ep.ep for ep in episodes if ep.ep in eligible and
                                 ep.start_ms >= begin and deadlines[ep.ep] < end}
                train = [i for i in indices if tags[i] is not None and mature[tags[i][0]] < begin]
                test = [i for i in indices if tags[i] is not None and tags[i][0] in test_episodes]
                model = fit_model([rows[i] for i in train], [tags[i] for i in train], points)
                if model is None:
                    continue
                seen.update(test_episodes)
                for i, p in zip(test, probabilities([rows[i] for i in test], model)):
                    heldout.append((rows[i], float(p)))
                    brier.append((p-int(tags[i][1]))**2)
            controls, evaluated = {}, []
            for cap in CAPS:
                controls[cap] = summarize(tape, labels, side, [r for r, _ in heldout if on_band(r, cap)], base, seen)
                for threshold in SCORE_THRESHOLDS:
                    metrics = summarize(tape, labels, side, [
                        r for r, p in heldout if p >= threshold and on_band(r, cap)
                    ], base, seen)
                    verdict = prior.gate(metrics, controls[cap], DEV_SCREEN)
                    evaluated.append(dict(cap_bps=cap, threshold=threshold, metrics=metrics, gate=verdict))
            training = [i for i in indices if tags[i] is not None and mature[tags[i][0]] <= tape.end[-1]]
            model = fit_model([rows[i] for i in training], [tags[i] for i in training], points)
            fitted[side][name] = model
            result[side][name] = {"oof_brier_score": float(np.mean(brier)) if brier else None,
                                  "oof_rows": len(heldout), "control_by_cap": controls,
                                  "grid": evaluated, "frontier": frontier(evaluated)}
            survivors = [point for point in evaluated if point["gate"]["passed"]]
            if survivors and model is not None and name != "clean_micro":
                best = max(survivors, key=lambda p: (
                    p["cap_bps"] <= 70, p["metrics"]["precision"], p["metrics"]["recall"],
                    -p["metrics"]["true_distance_bps"]["p90"]))
                incumbent = selections.get(side)
                if incumbent is None or best["metrics"]["precision"] > incumbent["metrics"]["precision"]:
                    selections[side] = dict(best, family=name)
    return result, fitted, selections, cuts


def comparator_signals(tape, states, portfolio):
    rules = {"raw_5m": [], "raw_10m": [], "raw_15m": [], "old_plus90": [],
             "old_plus120_HIGH": [], "HARD120_strict_scope": [], "Ultra_V2_strict_scope": []}
    for r in states:
        side, age = r["side"], r["age_s"]
        if age in (300, 600, 900):
            rules[f"raw_{age//60}m"].append(r)
        if age == 5400 or (side == "HIGH" and age == 7200):
            group = "balanced" if age == 5400 else "max_precision"
            k = int(np.searchsorted(tape.end, r["signal_ts_ms"]))
            reference = portfolio[group][side]["rule"]
            pos = r["features"].get("p011_position")
            if side == "LOW":
                # The historical report gives thresholds but does not commit
                # its original ret_180 extractor. Use an explicit M1 return.
                accepted = (r["retrace_bps"] >= reference[0]["threshold"]
                            and tape.close[k]/tape.close[k-180]-1 >= reference[1]["threshold"])
            else:
                accepted = pos is not None and pos <= reference[0]["threshold"]
            if accepted:
                rules["old_plus90" if age == 5400 else "old_plus120_HIGH"].append(r)
        if age == 7200:
            hard = HardCandidate(side, r["price"], r["candidate_ts_ms"], r["candidate_id"],
                                 r["pre_move_180_bps"], ["6h"])
            if next_signal(hard, now_ms=r["signal_ts_ms"], mark_price=r["signal_price"])[0]:
                rules["HARD120_strict_scope"].append(r)
        rule = ULTRA[side]
        if age == rule["age_minutes"]*60 and r["pre_move_180_bps"] > 0:
            mark, extreme = r["signal_price"], r["price"]
            retrace = (mark/extreme-1 if side == "LOW" else extreme/mark-1)*10_000
            if retrace >= max(rule["min_retrace_bps"], rule["min_fraction"]*r["pre_move_180_bps"]):
                rules["Ultra_V2_strict_scope"].append(r)
    return rules


def false_profiles(period, side):
    tape, states = period["tape"], period["early"]
    (_, episodes, eligible), _, deadline, targets = period["scope"]
    profile = []
    for row in period["candidates"]:
        if row["side"] != side:
            continue
        ep = first.assign_episode(row["candidate_ts_ms"], side, episodes)
        if ep is None or ep.ep not in eligible:
            continue
        target = targets[ep.target_label_id]
        i = row["bar_idx"]
        if (tape.start[i] == target["extreme_interval_start_ms"]
                and math.isclose(row["price"], target["extreme_price"], rel_tol=1e-10, abs_tol=1e-8)):
            continue
        stop = int(np.searchsorted(tape.start, deadline[ep.ep]))
        p = row["price"]
        sign = 1 if side == "LOW" else -1
        same = tape.low if sign == 1 else tape.high
        opposite = tape.high if sign == 1 else tape.low
        same_ts = tape.low_ts if sign == 1 else tape.high_ts
        opp_ts = tape.high_ts if sign == 1 else tape.low_ts
        first_extension = np.flatnonzero(sign*(same[i+1:stop]-p) < 0)
        end = i+1+int(first_extension[0]) if first_extension.size else stop
        # Include the extreme bar only when the tape proves the bounce came later.
        begin = i if opp_ts[i] > row["candidate_ts_ms"] else i+1
        path = opposite[begin:end]
        peak = begin+int(np.argmax(sign*path)) if len(path) else None
        stamp = int(same_ts[end]) if end < stop else deadline[ep.ep]
        bounce = max(0.0, sign*(float(opposite[peak])/p-1)*10_000) if peak is not None else 0.0
        profile.append({"id": row["candidate_id"], "candidate_ts_ms": row["candidate_ts_ms"],
                        "price": p, "terminal_price": target["extreme_price"],
                        "bounce_bps": bounce, "tactical_bounce_ge_30bps_offline": bounce >= 30,
                        "seconds_to_bounce_peak": (int(opp_ts[peak])-row["candidate_ts_ms"])/1000 if peak is not None else None,
                        "seconds_to_replacement_or_deadline": (stamp-row["candidate_ts_ms"])/1000,
                        "first_deterministic_m1_veto_ms": int(tape.end[end]) if end < stop else None,
                        "right_censored_at_next_extreme": end == stop,
                        "continuation_bps": max(0.0, -sign*(target["extreme_price"]/p-1)*10_000)})
    associations = []
    tags = outcomes(states, period["scope"])
    for age in (180, 300, 600):
        groups = [{}, {}]
        for r, tag in zip(states, tags):
            if r["side"] != side or r["age_s"] != age or tag is None:
                continue
            for name, value in r["features"].items():
                groups[int(tag[1])].setdefault(name, []).append(value)
        for name in groups[0].keys() & groups[1].keys():
            f, t = groups[0][name], groups[1][name]
            if min(len(f), len(t)) < 8:
                continue
            lo, hi = np.quantile([*f, *t], (0.25, 0.75))
            a, b = float(np.median(f)), float(np.median(t))
            if hi > lo:
                associations.append(dict(age_s=age, point=features.point_id(name), feature=name,
                                         true_median=b, false_median=a, true_n=len(t), false_n=len(f),
                                         median_gap_iqr=float((b-a)/(hi-lo))))
    associations.sort(key=lambda x: (-abs(x["median_gap_iqr"]), x["feature"], x["age_s"]))
    return {"candidates": profile, "associations": associations,
            "same_bar_limit": "The replacement bar's reversal amplitude is excluded if ordering is ambiguous."}


def inventory(master, clean_index, decision_sampling="legacy_age_grid"):
    periods, descriptors = {}, {}
    for info, bars, labels in sources.read_master(master):
        tape, rows, candidates = features.m1_states(bars, decision_sampling=decision_sampling)
        name = info["folder"]
        early = (rows if decision_sampling == "completed_m1_events" else
                 [row for row in rows if row["age_s"] in features.EARLY_AGES])
        matched = 0
        if name == prior.PERIODS[0] and clean_index:
            for row in early:
                additional = features.clean_micro_features(row, clean_index)
                matched += bool(features.available_points(additional) - QUALITY_ONLY)
                row["clean_features"] = additional
        scope = signal_scope(tape, labels)
        periods[name] = dict(tape=tape, labels=labels, early=early, all=rows,
                             scope=scope, candidates=candidates)
        counts = Counter(i for row in early for i in features.available_points(row["features"]))
        clean_counts = Counter(i for row in early
                               for i in features.available_points(row.get("clean_features", {})))
        descriptors[name] = {"tape_rows": len(bars), "decision_rows": len(early),
                             "candidates": len(candidates), "clean_matches": matched,
                             "strict_finalized": dict(Counter(lab["side"] for lab in scope[0][0])),
                             "actionable_episodes": dict(Counter(ep.target_side for ep in scope[0][1]
                                                                 if ep.ep in scope[0][2])),
                             "counts": counts, "clean_counts": clean_counts,
                             "period_utc": [info["start"], info["end"]],
                             "source": f"{sources.MASTER_ID}/{name}/compact_1m.jsonl.gz"}
    return periods, descriptors


def run(args):
    clean_index = {}
    clean = {"run_id": sources.CLEAN_PENDING_RUN, "status": "blocked",
             "reason": "No certified archive supplied for the upgraded producer contract"}
    if args.clean_cache:
        clean_index = sources.read_clean_cache(args.clean_cache, args.clean_sha256)
        clean = dict(status="verified", sha256=args.clean_sha256, producer_contract=features.MICRO_CONTRACT)
    live = sources.read_live_coverage(args.live_checkpoint)
    periods, descriptors = inventory(args.master, clean_index)
    coverage = sources.coverage(descriptors, live, clean)
    args.output.mkdir(parents=True, exist_ok=True)
    dump(args.output/"FULL_116_DATA_COVERAGE_MATRIX.json", coverage)
    coverage_md = args.output/"FULL_116_DATA_COVERAGE_MATRIX.md"
    coverage_md.write_text(sources.coverage_markdown(coverage), encoding="utf-8")
    print("DATA AUDIT", {name: (r["decision_rows"], len(r["counts"]), r["clean_matches"])
                         for name, r in descriptors.items()}, flush=True)
    development = periods[prior.PERIODS[0]]
    # Mask the rich namespace in both common-plane ablations.
    kinds = {"structure": features.PRICE_POINTS, "common_trajectory": features.HISTORICAL_POINTS}
    if clean_index and descriptors[prior.PERIODS[0]]["clean_matches"]:
        kinds["clean_micro"] = None
    dev, fits, selected, cuts = develop(development, kinds)
    fitted_ids = {features.point_id(key) for models in fits.values() for model in models.values()
                  if model for key in model["feature_names"]}
    frozen = {}
    for side, choice in selected.items():
        frozen[side] = {"family": choice["family"], "cap_bps": choice["cap_bps"],
                        "threshold": choice["threshold"], "model": fits[side][choice["family"]]}
    model_doc = {"status": "development_screen_only", "frozen_for_transfer": frozen,
                 "development_fits": fits, "gate": DEV_SCREEN, "cuts_ms": cuts,
                 "source_hashes": {Path(mod.__file__).name: prior.file_sha(mod.__file__)
                                   for mod in (m1, features, sources, prior, first)},
                 "runner_sha256": prior.file_sha(__file__), "real_orders": False}
    model_path = args.output/"FULL_116_DEVELOPMENT_MODELS.json"
    dump(model_path, model_doc)
    model_sha = prior.file_sha(model_path)
    print("DEVELOPMENT", {side: item["family"] for side, item in selected.items()},
          "MODEL SHA", model_sha, flush=True)
    portfolio = json.loads(PORTFOLIO.read_text())
    comparators, transfer = {}, {}
    for name, p in periods.items():
        tape, labels, scope = p["tape"], p["labels"], p["scope"][0]
        signals = comparator_signals(tape, p["all"], portfolio)
        comparators[name] = {
            side: {key: summarize(tape, labels, side, [row for row in records if row["side"] == side],
                                  scope, keep_records=key.startswith(("old_", "HARD", "Ultra")))
                   for key, records in signals.items() if key != "old_plus120_HIGH" or side == "HIGH"}
            for side in m1.SIDES
        }
        if name == prior.PERIODS[0]:
            continue
        transfer[name] = {}
        for side, spec in frozen.items():
            rows = [r for r in p["early"] if r["side"] == side and on_band(r, spec["cap_bps"])]
            accepted = [r for r, prob in zip(rows, probabilities(rows, spec["model"]))
                        if prob >= spec["threshold"]]
            metrics = summarize(tape, labels, side, accepted, scope, keep_records=True)
            control = summarize(tape, labels, side, rows, scope)
            transfer[name][side] = {"metrics": metrics, "control": control,
                                    "gate": prior.gate(metrics, control, {
                                        "episodes": 20, "true_first": 5, "precision": 0.55,
                                        "recall": 0.20, "precision_gain": 0.12})}
    for side in m1.SIDES:
        profile = {name: false_profiles(p, side) for name, p in periods.items()}
        data = json.dumps(profile, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        (args.output/f"FALSE_LOCAL_SIGNATURES_{side}.json.gz").write_bytes(gzip.compress(data, mtime=0))
    survived = {side: bool(frozen.get(side)) and all(
        by_side[side]["gate"]["passed"] for by_side in transfer.values()) for side in m1.SIDES}
    result = {"target": "STRICT H1 L6/K2 TERMINAL", "research_only": True, "real_orders": False,
              "model_file_sha256": model_sha, "data": coverage["periods"], "clean": clean,
              "development": dev, "selected": selected, "transfer": transfer,
              "all_transfer_gates_passed": survived,
              "strict_comparators": comparators,
              "comparability": "HARD120 and Ultra thresholds are rescored on shared strict candidates. "
                              "Historical L3/K1 results and original per-rule candidate cohorts are separate. "
                              "LOW +120 extractor is unavailable; LOW +90 uses explicit trailing M1 return.",
              "sealed": "unopened", "forward": "not used", "score_thresholds": SCORE_THRESHOLDS,
              "distance_caps_bps": CAPS}
    dump(args.output/"FULL_116_FIRST_SIGNAL_REPLAY.json", result)
    coverage = sources.coverage(descriptors, live, clean, fitted_ids)
    dump(args.output/"FULL_116_DATA_COVERAGE_MATRIX.json", coverage)
    coverage_md.write_text(sources.coverage_markdown(coverage), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-checkpoint", type=Path)
    parser.add_argument("--clean-cache", type=Path)
    parser.add_argument("--clean-sha256")
    args = parser.parse_args()
    if bool(args.clean_cache) != bool(args.clean_sha256):
        parser.error("clean cache requires the independently obtained artifact digest")
    run(args)


if __name__ == "__main__":
    main()
