from dataclasses import fields
from datetime import datetime, timedelta, timezone
import argparse
import json
import math
from pathlib import Path
import sys
import time

from .engine import ResearchEngine
from .model import Config, SYMBOLS, finite_number
from .output import Output
from .sources import SourceError, historical, parse_symbols, replay, utc_date


def main(argv=None):
    parser = argparse.ArgumentParser(description="Caterpillar public-data PAPER research; no order methods or production integration")
    parser.add_argument("mode", choices=("historical_research", "realtime_audit", "replay", "hourly_report"))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", type=Path, help="Frozen Config JSON; no fitting occurs")
    parser.add_argument("--start-date", help="UTC inclusive; default 60 completed days ago")
    parser.add_argument("--end-date", help="UTC exclusive; default today 00:00 UTC")
    parser.add_argument("--split-date", help="UTC held-out restart; freeze any discovery-derived configuration BEFORE evaluation")
    parser.add_argument("--cache", default=".cache/archives")
    parser.add_argument("--allow-ohlcv-fallback", action="store_true")
    parser.add_argument("--duration-seconds", type=float, default=21600)
    parser.add_argument("--hours", type=float, help="Convenience alias for realtime duration in hours")
    parser.add_argument("--days", type=int, help="Convenience historical lookback when --start-date is omitted")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint.json in the output directory")
    parser.add_argument("--market-context", action="store_true", help="Realtime research only: log public L1 spread/depth and liquidation context")
    parser.add_argument("--latest", action="store_true", help="hourly_report: render the latest research_status.json")
    parser.add_argument("--reorder-seconds", type=float, default=2)
    parser.add_argument("--max-lag-seconds", type=float, default=15)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--source-manifest", type=Path, help="Replay source config/phase; raw_trades.jsonl discovers its sibling run_manifest.json automatically")
    parser.add_argument("--record-trades", action="store_true", help="Write accepted raw trades; potentially very large")
    args = parser.parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
        source_meta = None
        manifest_path = args.source_manifest
        if args.mode == "replay" and args.input and manifest_path is None and args.input.name == "raw_trades.jsonl":
            sibling = args.input.parent/"run_manifest.json"
            if sibling.is_file():
                manifest_path = sibling
        if manifest_path:
            if args.mode != "replay":
                raise ValueError("--source-manifest is only supported for replay")
            source_meta = json.loads(manifest_path.read_text())
            if not isinstance(source_meta, dict) or not isinstance(source_meta.get("config"), dict):
                raise ValueError("Source manifest must contain a config object")
        data = json.loads(args.config.read_text()) if args.config else source_meta["config"] if source_meta else {}
        if not isinstance(data, dict) or not set(data) <= {f.name for f in fields(Config)}:
            raise ValueError("Unknown configuration keys or non-object config")
        if "exit_models" in data:
            data["exit_models"] = tuple(data["exit_models"])
        config = Config(**data)
        split = utc_date(args.split_date).timestamp() if args.split_date else None
        if source_meta and not args.split_date:
            source_metadata = source_meta.get("metadata", {})
            if not isinstance(source_metadata, dict):
                raise ValueError("Source manifest metadata must be an object")
            split = source_metadata.get("split_ts")
            if split is None and source_meta.get("mode") == "realtime_audit":
                split = 0.0
            if split is not None and (not finite_number(split) or split < 0):
                raise ValueError("Invalid source split_ts")
        end = utc_date(args.end_date) if args.end_date else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = utc_date(args.start_date) if args.start_date else end-timedelta(days=60)
        if args.mode == "historical_research" and (start >= end or end > datetime.now(timezone.utc)
                or (split is not None and not start.timestamp() < split < end.timestamp())):
            raise ValueError("Require start < split < end, or start < end without split")
        if args.mode == "replay" and not args.input:
            raise ValueError("replay requires --input")
        if args.mode != "replay" and args.input:
            raise ValueError("--input is only supported for replay")
        if args.mode != "historical_research" and (args.start_date or args.end_date or args.allow_ohlcv_fallback):
            raise ValueError("--start-date, --end-date and OHLCV fallback apply only to historical_research")
        if args.mode == "realtime_audit":
            if args.split_date:
                raise ValueError("Realtime is a separate frozen out-of-sample run; --split-date applies to history/replay")
            # The frozen realtime audit is evaluation from its first observation,
            # not an implicit discovery period that can never produce OOS buckets.
            split = 0.0
            if not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0:
                raise ValueError("--duration-seconds must be finite and positive")
            if not math.isfinite(args.reorder_seconds) or args.reorder_seconds < 0 or not math.isfinite(args.max_lag_seconds) or args.max_lag_seconds <= args.reorder_seconds:
                raise ValueError("Require finite 0 <= reorder-seconds < max-lag-seconds")
        metadata = {"start": start.isoformat(), "end": end.isoformat()} if args.mode == "historical_research" else {}
        metadata["split_ts"] = split
        if args.mode == "realtime_audit":
            metadata["phase_policy"] = "evaluation from first realtime observation; configuration frozen before collection"
        if args.input:
            from .sources import file_sha
            metadata["input_sha256"] = file_sha(args.input)
        if source_meta:
            metadata["source_manifest"] = {"sha256": file_sha(manifest_path), "package_version": source_meta.get("package_version"),
                                          "package_source_sha256": source_meta.get("package_source_sha256"),
                                          "schema_version": source_meta.get("schema_version"), "config_overridden": bool(args.config)}
        output = Output(args.output, config, symbols, args.mode, metadata)
    except (ValueError, OSError, TypeError) as exc:
        parser.error(str(exc))
    engine = ResearchEngine(output, config, symbols, split, args.record_trades)
    code, status = 0, "completed"
    try:
        if args.mode == "historical_research":
            status = historical(engine, args.cache, start, end, args.allow_ohlcv_fallback)
        elif args.mode == "realtime_audit":
            from .realtime import realtime
            status = realtime(engine, args.duration_seconds, args.reorder_seconds, args.max_lag_seconds)
        else:
            replay(engine, args.input)
            complete = True
            for symbol, profile in engine.profiles.items():
                accepted = profile.counts.get("accepted_trades", 0)
                rejected = sum(profile.counts.get("quality/"+reason, 0) for reason in ("invalid_trade", "late_trade"))
                gap_events = sum(n for key, n in profile.counts.items() if key.startswith("quality/")
                                 and key not in ("quality/duplicate", "quality/evaluation_boundary", "quality/invalid_trade", "quality/late_trade"))
                complete = complete and bool(accepted) and not rejected and not gap_events
                engine.coverage.append({"symbol": symbol, "source": "replay", "accepted": accepted,
                                        "rejected_invalid_or_late": rejected, "gap_or_quality_events": gap_events,
                                        "first_ts": profile.first, "last_ts": profile.last,
                                        "status": "observed" if accepted and not rejected and not gap_events else "unavailable_or_partial"})
            status = "completed" if complete else "incomplete_coverage"
        if status != "completed":
            code = 2
    except KeyboardInterrupt:
        status, code = "interrupted", 130
    except Exception as exc:
        # Keep partial evidence but return failure. Network exception strings may contain proxy credentials.
        status, code = "failed/"+type(exc).__name__, 1
        print(f"Research failed: {type(exc).__name__}; partial evidence retained", file=sys.stderr)
        if isinstance(exc, SourceError):
            # Our source adapters construct these from public identifiers, never raw proxy exception strings.
            output.meta["metadata"]["runtime_error"] = str(exc)
            print(str(exc), file=sys.stderr)
    finally:
        engine.finish(status)
    print(f"{status}: {Path(args.output).resolve()}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
