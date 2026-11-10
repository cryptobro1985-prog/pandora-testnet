from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path

from research.hype_quant.features import FeatureState
from research.hype_quant.live_daemon import Tailer, append_jsonl, event_ts
from research.hype_movement_signature.learner import MovementSignatureLearner


def load_pickle(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return default


def save_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(obj, f)
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture-root", type=Path, required=True)
    ap.add_argument("--checkpoint-dir", type=Path, required=True)
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--poll-seconds", type=float, default=0.5)
    ap.add_argument("--sample-seconds", type=int, default=5)
    ap.add_argument("--round-trip-cost", type=float, default=0.0012)
    ap.add_argument("--adverse-penalty", type=float, default=1.0)
    args = ap.parse_args()
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    learner_path = args.checkpoint_dir / "movement_signature.pkl"
    feature_path = args.checkpoint_dir / "feature_state.pkl"
    learner = load_pickle(
        learner_path,
        MovementSignatureLearner(
            round_trip_cost=args.round_trip_cost,
            adverse_penalty=args.adverse_penalty,
        ),
    )
    state = load_pickle(feature_path, FeatureState())
    tail = Tailer()

    actions_path = args.checkpoint_dir / "MOVEMENT_SIGNATURE_ACTIONS.jsonl"
    gaps_path = args.checkpoint_dir / "MOVEMENT_SIGNATURE_GAPS.jsonl"
    report_path = args.checkpoint_dir / "MOVEMENT_SIGNATURE_REPORT.json"
    coverage_path = args.checkpoint_dir / "FEATURE_COVERAGE_116.json"
    actions_path.touch(exist_ok=True)
    gaps_path.touch(exist_ok=True)

    started = time.time()
    deadline = started + args.minutes * 60
    next_sample_ms = 0
    next_save = 0.0
    last_seen_ts = getattr(state, "last_ts_ms", None)
    processed_micro = sampled = raw_frames = market_rows = struct_rows = 0

    while time.time() < deadline:
        events = []
        for path in sorted(args.capture_root.rglob("HYPE_live_raw_frames.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("raw", row), 0, "raw", row))
        for path in sorted(args.capture_root.rglob("HYPE_market_context.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("market", row), 1, "market", row))
        for path in sorted(args.capture_root.rglob("HYPE_structural_context_1m.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("struct", row), 2, "struct", row))
        for path in sorted(args.capture_root.rglob("HYPE_live_microstructure_1s.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("micro", row), 3, "micro", row))
        events.sort(key=lambda z: (z[0], z[1]))

        for ts, _, kind, row in events:
            if ts <= 0:
                continue
            if kind == "raw":
                state.update_raw_frame(row)
                raw_frames += 1
                continue
            if kind == "market":
                state.update_market_context(row)
                market_rows += 1
                continue
            if kind == "struct":
                state.update_structural_context(row)
                struct_rows += 1
                continue

            if last_seen_ts is not None and ts <= last_seen_ts:
                continue
            if last_seen_ts is not None:
                gap_s = (ts - last_seen_ts) / 1000.0
                if gap_s > 10:
                    append_jsonl(
                        gaps_path,
                        {
                            "from_ts_ms": last_seen_ts,
                            "to_ts_ms": ts,
                            "gap_seconds": gap_s,
                            "action": "clear_pending_labels_after_gap",
                        },
                    )
                    learner.pending.clear()
                    state.prices.clear()
            last_seen_ts = ts

            try:
                price, x = state.update_micro(row)
            except Exception as exc:
                append_jsonl(gaps_path, {"ts_ms": ts, "feature_error": repr(exc)})
                continue

            processed_micro += 1
            if ts < next_sample_ms:
                continue
            next_sample_ms = ts + args.sample_seconds * 1000

            decision = learner.observe(ts, price, x)
            sampled += 1
            append_jsonl(
                actions_path,
                {
                    "ts_ms": ts,
                    "price": price,
                    "feature_count": len(x),
                    "decision": decision,
                },
            )

        now = time.time()
        if now >= next_save:
            save_pickle(learner_path, learner)
            save_pickle(feature_path, state)
            coverage = state.coverage_report()
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            report = learner.report()
            report.update(
                {
                    "processed_micro_rows": processed_micro,
                    "sampled_states": sampled,
                    "raw_frames_consumed": raw_frames,
                    "market_context_rows_consumed": market_rows,
                    "structural_context_rows_consumed": struct_rows,
                    "last_seen_ts_ms": last_seen_ts,
                    "feature_contract": coverage,
                    "updated_ts_ms": int(now * 1000),
                    "capture_root": str(args.capture_root),
                    "research_only": True,
                    "real_orders": False,
                }
            )
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            next_save = now + 60

        if not events:
            time.sleep(args.poll_seconds)

    save_pickle(learner_path, learner)
    save_pickle(feature_path, state)
    coverage = state.coverage_report()
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    report = learner.report()
    report.update(
        {
            "processed_micro_rows": processed_micro,
            "sampled_states": sampled,
            "last_seen_ts_ms": last_seen_ts,
            "feature_contract": coverage,
            "completed_ts_ms": int(time.time() * 1000),
            "research_only": True,
            "real_orders": False,
        }
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
