#!/usr/bin/env python3
"""Fault-tolerant research-only supervisor for HYPE forward capture.

A "chunk" is only a storage/provenance boundary. It is NOT a recovery timeout.
The supervisor polls both collectors every few seconds. If either collector exits
unexpectedly, the sibling is stopped, already-flushed files are preserved in the
current chunk directory, and a new pair starts almost immediately in a new chunk.

No trading endpoints. No order placement.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


POLL_SECONDS = 2.0
BASE_RESTART_BACKOFF_SECONDS = 2.0
MAX_RESTART_BACKOFF_SECONDS = 15.0


def terminate(proc: subprocess.Popen, grace_seconds: float = 5.0) -> int | None:
    if proc.poll() is not None:
        return proc.returncode
    proc.terminate()
    try:
        return proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=5)


def run_pair(root: Path, idx: int, requested_minutes: int, global_deadline: float) -> dict:
    out = root / "chunks" / f"chunk_{idx:04d}"
    out.mkdir(parents=True, exist_ok=True)

    live_log = (out / "live.log").open("w", encoding="utf-8")
    ctx_log = (out / "context.log").open("w", encoding="utf-8")
    start = time.time()

    live = subprocess.Popen(
        [
            sys.executable,
            "research/hype_local_v5/research.py",
            "--mode", "live",
            "--minutes", str(requested_minutes),
            "--output", str(out),
        ],
        stdout=live_log,
        stderr=subprocess.STDOUT,
    )
    ctx = subprocess.Popen(
        [
            sys.executable,
            "research/hype_local_v5/context_capture.py",
            "--minutes", str(requested_minutes),
            "--output", str(out),
        ],
        stdout=ctx_log,
        stderr=subprocess.STDOUT,
    )

    reason = "completed"
    failed_component = None

    try:
        while True:
            live_rc = live.poll()
            ctx_rc = ctx.poll()

            if live_rc is not None and ctx_rc is not None:
                reason = "completed" if live_rc == 0 and ctx_rc == 0 else "collector_exit"
                if live_rc != 0 and ctx_rc == 0:
                    failed_component = "microstructure"
                elif ctx_rc != 0 and live_rc == 0:
                    failed_component = "structural_context"
                elif live_rc != 0 or ctx_rc != 0:
                    failed_component = "both_or_mixed"
                break

            # If one side dies while the other is still alive, fail over now;
            # do not wait for the storage chunk boundary.
            if live_rc is not None and ctx_rc is None:
                reason = "microstructure_exit"
                failed_component = "microstructure"
                terminate(ctx)
                break
            if ctx_rc is not None and live_rc is None:
                reason = "structural_context_exit"
                failed_component = "structural_context"
                terminate(live)
                break

            if time.time() >= global_deadline:
                reason = "global_deadline"
                terminate(live)
                terminate(ctx)
                break

            time.sleep(POLL_SECONDS)
    finally:
        # Ensure no orphan process survives a restart.
        terminate(live)
        terminate(ctx)
        live_log.close()
        ctx_log.close()

    end = time.time()
    rec = {
        "chunk": idx,
        "requested_minutes": requested_minutes,
        "started_ts_ms": int(start * 1000),
        "ended_ts_ms": int(end * 1000),
        "observed_wall_seconds": end - start,
        "live_rc": live.returncode,
        "context_rc": ctx.returncode,
        "reason": reason,
        "failed_component": failed_component,
        "restart_poll_seconds": POLL_SECONDS,
        "path": str(out),
    }
    (out / "CHUNK_STATUS.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def capture_evidence(root: Path) -> dict:
    """Count usable observations; elapsed worker lifetime is not market evidence."""
    counts = {"public_trade_frames": 0, "priced_micro_rows": 0, "h1_context_rows": 0}
    malformed = 0
    for filename, channel in (("HYPE_live_raw_frames.jsonl", "raw"),
                              ("HYPE_live_microstructure_1s.jsonl", "micro"),
                              ("HYPE_market_context.jsonl", "context")):
        for path in root.rglob(filename):
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            continue
                        if channel == "raw":
                            raw = row.get("raw_text")
                            msg = json.loads(raw) if isinstance(raw, str) else raw
                            if (isinstance(msg, dict) and
                                    str(msg.get("topic", "")).startswith("publicTrade.HYPEUSDT") and
                                    isinstance(msg.get("data"), list) and msg["data"]):
                                counts["public_trade_frames"] += 1
                        elif channel == "micro":
                            price = float(row.get("mid") or 0)
                            if math.isfinite(price) and price > 0 and int(row.get("ts_ms") or 0) > 0:
                                counts["priced_micro_rows"] += 1
                        elif isinstance(row.get("candles"), dict) and row["candles"].get("60"):
                            counts["h1_context_rows"] += 1
                    except (ValueError, TypeError, OverflowError):
                        malformed += 1
    return {**counts, "malformed_rows": malformed,
            "usable": all(counts.values()),
            "note": "Usable observations only; does not establish full-window coverage or prediction quality."}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--chunk-minutes", type=int, default=20)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    started = time.time()
    deadline = started + args.minutes * 60
    manifest_path = args.output / "RESILIENT_CAPTURE_MANIFEST.json"

    manifest = {
        "research_only": True,
        "symbol": "HYPEUSDT",
        "target_minutes": args.minutes,
        "storage_chunk_minutes": args.chunk_minutes,
        "recovery_semantics": "seconds-level watchdog; chunk size is not recovery timeout",
        "watchdog_poll_seconds": POLL_SECONDS,
        "max_restart_backoff_seconds": MAX_RESTART_BACKOFF_SECONDS,
        "git_sha": os.getenv("GITHUB_SHA"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "started_ts_ms": int(started * 1000),
        "chunks": [],
    }

    idx = 0
    consecutive_failures = 0

    while time.time() < deadline - 2:
        idx += 1
        remaining_seconds = max(1.0, deadline - time.time())
        requested_minutes = max(
            1,
            min(args.chunk_minutes, int(math.ceil(remaining_seconds / 60.0))),
        )

        rec = run_pair(args.output, idx, requested_minutes, deadline)
        manifest["chunks"].append(rec)
        write_manifest(manifest_path, manifest)

        if rec["reason"] == "global_deadline":
            break

        healthy = rec["live_rc"] == 0 and rec["context_rc"] == 0
        if healthy:
            consecutive_failures = 0
            # Healthy chunk finished: start the next storage chunk immediately.
            continue

        consecutive_failures += 1
        # Transient failure: restart in seconds, never wait for the 20m boundary.
        backoff = min(
            MAX_RESTART_BACKOFF_SECONDS,
            BASE_RESTART_BACKOFF_SECONDS * (2 ** max(0, consecutive_failures - 1)),
        )
        remaining = deadline - time.time()
        if remaining <= 2:
            break
        time.sleep(min(backoff, max(0.0, remaining - 1)))

    manifest["completed_ts_ms"] = int(time.time() * 1000)
    manifest["chunks_with_any_data_process"] = sum(
        1 for x in manifest["chunks"]
        if x["observed_wall_seconds"] > 0
    )
    manifest["healthy_chunks"] = sum(
        1 for x in manifest["chunks"]
        if x["live_rc"] == 0 and x["context_rc"] == 0
    )
    manifest["restart_events"] = sum(
        1 for x in manifest["chunks"]
        if x["reason"] not in ("completed", "global_deadline")
    )
    manifest["evidence"] = capture_evidence(args.output)
    write_manifest(manifest_path, manifest)

    if not manifest["chunks"]:
        raise SystemExit(2)

    print(json.dumps(manifest), flush=True)
    if not manifest["evidence"]["usable"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
