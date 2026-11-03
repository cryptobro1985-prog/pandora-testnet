from dataclasses import fields
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import sys

from .engine import ResearchEngine
from .model import Config, SYMBOLS
from .output import Output
from .sources import historical, parse_symbols, replay, utc_date


def main(argv=None):
    parser = argparse.ArgumentParser(description="Caterpillar public-data PAPER research; no order methods or production integration")
    parser.add_argument("mode", choices=("historical_research", "realtime_audit", "replay"))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", type=Path, help="Frozen Config JSON; no fitting occurs")
    parser.add_argument("--start-date", help="UTC inclusive; default 60 completed days ago")
    parser.add_argument("--end-date", help="UTC exclusive; default today 00:00 UTC")
    parser.add_argument("--split-date", help="UTC held-out restart; freeze any discovery-derived configuration BEFORE evaluation")
    parser.add_argument("--cache", default=".cache/archives")
    parser.add_argument("--allow-ohlcv-fallback", action="store_true")
    parser.add_argument("--duration-seconds", type=float, default=21600)
    parser.add_argument("--reorder-seconds", type=float, default=2)
    parser.add_argument("--max-lag-seconds", type=float, default=15)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--record-trades", action="store_true", help="Write accepted raw trades; potentially very large")
    args = parser.parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
        data = json.loads(args.config.read_text()) if args.config else {}
        if not isinstance(data, dict) or not set(data) <= {f.name for f in fields(Config)}:
            raise ValueError("Unknown configuration keys or non-object config")
        if "exit_models" in data:
            data["exit_models"] = tuple(data["exit_models"])
        config = Config(**data)
        split = utc_date(args.split_date).timestamp() if args.split_date else None
        end = utc_date(args.end_date) if args.end_date else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = utc_date(args.start_date) if args.start_date else end-timedelta(days=60)
        if args.mode == "historical_research" and (start >= end or (split and not start.timestamp() < split < end.timestamp())):
            raise ValueError("Require start < split < end, or start < end without split")
        if args.mode == "replay" and not args.input:
            raise ValueError("replay requires --input")
        metadata = {"start": start.isoformat(), "end": end.isoformat()} if args.mode == "historical_research" else {}
        if args.input:
            from .sources import file_sha
            metadata["input_sha256"] = file_sha(args.input)
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
            accepted = sum(p.counts.get("accepted_trades", 0) for p in engine.profiles.values())
            status = "completed" if accepted else "incomplete_coverage"
        if status != "completed":
            code = 2
    except KeyboardInterrupt:
        status, code = "interrupted", 130
    except Exception as exc:
        # Keep partial evidence but return failure. Network exception strings may contain proxy credentials.
        status, code = "failed/"+type(exc).__name__, 1
        print(f"Research failed: {type(exc).__name__}; partial evidence retained", file=sys.stderr)
    finally:
        engine.finish(status)
    print(f"{status}: {Path(args.output).resolve()}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
