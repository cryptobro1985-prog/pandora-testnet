"""Human-readable progress, hourly snapshots and conservative strategy synthesis."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _latest(group):
    return asdict(group[-1]) if group else None


def _top_hypotheses(profile_result, prefix=None, min_n=1, limit=8):
    rows = []
    for key, row in profile_result.get("hypotheses", {}).items():
        if prefix and prefix not in key:
            continue
        if row.get("n", 0) < min_n:
            continue
        mean = row.get("mean_net_bps")
        if not _finite(mean):
            continue
        detail = {}
        parts = key.split("/")
        metrics = profile_result.get("metrics", {})
        if len(parts) == 4 and parts[1] == "feature":
            base = "pattern/"+parts[2]+"/"+parts[3]+"/"
            detail = {
                "median_pnl_bps": (metrics.get(base+"net_bps") or {}).get("recent_median"),
                "median_mfe_bps": (metrics.get(base+"mfe_bps") or {}).get("recent_median"),
                "median_mae_bps": (metrics.get(base+"mae_bps") or {}).get("recent_median"),
                "median_mfe_capture_ratio": (metrics.get(base+"mfe_capture_ratio") or {}).get("recent_median"),
            }
        elif len(parts) == 4 and parts[1] == "local":
            base = "local_pattern/"+parts[2]+"/"+parts[3]+"/"
            detail = {
                "median_pnl_bps": (metrics.get(base+"close_bps") or {}).get("recent_median"),
                "median_mfe_bps": (metrics.get(base+"mfe_bps") or {}).get("recent_median"),
                "median_mae_bps": (metrics.get(base+"mae_bps") or {}).get("recent_median"),
                "median_mfe_capture_ratio": (metrics.get(base+"mfe_capture_ratio") or {}).get("recent_median"),
            }
        rows.append({
            "hypothesis": key,
            "samples": row["n"],
            "positive_fraction": row.get("positive_fraction"),
            "mean_net_bps": mean,
            "observed_utc_days": row.get("observed_utc_days", 0),
            "daily_mean_median_net_bps": row.get("daily_mean_median_net_bps"),
            **detail,
        })
    rows.sort(key=lambda x: (x["samples"] >= min_n, x["mean_net_bps"], x["samples"]), reverse=True)
    return rows[:limit]


def token_snapshot(engine, symbol):
    state = engine.states[symbol]
    profile = engine.profiles[symbol].result()
    flow = state.history[-1] if state.history else None
    positions = {}
    for model, book in state.books.items():
        if book.position:
            p = asdict(book.position)
            p["mfe_giveback_usd"] = p["mfe"] - p["current"]
            positions[model] = p
    quality = {k: v for k, v in profile["counts"].items() if k.startswith("quality/")}
    research_pending = []
    tracker = getattr(state, "research_locals", None)
    if tracker is not None:
        research_pending = [asdict(x) for x in tracker.pending.values()]
    findings = _top_hypotheses(profile, min_n=3)
    confirmed_low = _latest(state.locals["LOW"])
    confirmed_high = _latest(state.locals["HIGH"])
    return {
        "symbol": symbol,
        "data_coverage": {
            "first_event_ts": profile.get("first_event_ts"),
            "last_event_ts": profile.get("last_event_ts"),
            "accepted_trades": profile["counts"].get("accepted_trades", 0),
            "flow_blocks": profile["counts"].get("flow_blocks", 0),
            "quality_events": quality,
        },
        "current_price": state.last_price,
        "h1": {
            "last_confirmed_low": confirmed_low,
            "last_confirmed_high": confirmed_high,
            "forming": asdict(state.candidate) if state.candidate else None,
            "multi_hypothesis_forming": research_pending,
            "closed_bars": len(state.h1.history) if state.h1 else 0,
        },
        "structure": state.trend,
        "recent_flow": flow,
        "market_context": state.market_context or None,
        "paper": {
            "open_positions": positions,
            "closed_by_model": {m: profile["counts"].get(m + "/closed", 0) for m in engine.config.exit_models},
            "censored_by_model": {m: profile["counts"].get(m + "/censored", 0) for m in engine.config.exit_models},
            "entry_counts": {
                "accepted": sum(v for k, v in profile["counts"].items() if k.startswith("research_entry/accepted/")),
                "rejected": sum(v for k, v in profile["counts"].items() if k.startswith("research_entry/rejected/")),
            },
            "reentry_counts": {
                "ready": sum(v for k, v in profile["counts"].items() if k.startswith("research_reentry/ready/")),
                "rejected": sum(v for k, v in profile["counts"].items() if k.startswith("research_reentry/rejected/")),
            },
        },
        "preliminary_findings": findings,
        "confidence": {
            "status": "INSUFFICIENT_DATA" if not findings else "PRELIMINARY",
            "warning": "Hourly evidence is descriptive; multi-day validation is required before a 24/7 rule is promoted.",
        },
    }


def build_status(engine, ts=None, reason="heartbeat"):
    ts = float(ts if ts is not None else datetime.now(timezone.utc).timestamp())
    tokens = {symbol: token_snapshot(engine, symbol) for symbol in engine.states}
    evidence = Counter()
    for row in tokens.values():
        for finding in row["preliminary_findings"]:
            if finding["mean_net_bps"] > 0:
                evidence[finding["hypothesis"]] += 1
    cross = [{"hypothesis": key, "positive_tokens": n}
             for key, n in evidence.most_common(12)]
    return {
        "ts": ts,
        "iso_utc": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
        "reason": reason,
        "mode": engine.output.meta.get("mode"),
        "run_status": engine.output.meta.get("status", "running"),
        "config_sha256": engine.config.digest,
        "symbols": list(engine.states),
        "tokens": tokens,
        "cross_token_findings": cross,
        "what_we_know": [
            "Only causally available observations are eligible for decisions.",
            "H1 locals and executed-flow observations are stored separately.",
            "LONG and SHORT research hypotheses are evaluated independently.",
        ],
        "what_we_suspect": cross[:5],
        "what_is_not_proven_yet": [
            "profitability", "optimal local definition", "optimal thresholds",
            "market-maker identity", "funding/market-impact realism",
            "24/7 robustness without multi-day out-of-sample evidence",
        ],
        "data_quality": {
            symbol: tokens[symbol]["data_coverage"]["quality_events"]
            for symbol in tokens
        },
    }


def persist_status(engine, ts=None, reason="heartbeat", hourly=False):
    row = build_status(engine, ts, reason)
    engine.output.save_json("research_status.json", row)
    if hourly:
        engine.output.emit("hourly_snapshots", row)
        engine.output.flush()
        # Render/background jobs may not have durable local storage. Emit the
        # complete hourly snapshot to stdout as a recoverable observability
        # surface; it contains public market research only and no secrets.
        print("CATERPILLAR_HOURLY_SNAPSHOT "+json.dumps(row, ensure_ascii=False, separators=(",",":")), flush=True)
    return row


def synthesize(engine, status):
    """Produce conservative per-token strategy candidates from accumulated evidence.

    This function does not fit thresholds and never labels a candidate deployment-ready.
    """
    tokens = {}
    universal = Counter()
    for symbol, profile in engine.profiles.items():
        result = profile.result()
        feature_rows = _top_hypotheses(result, "/feature/", engine.config.min_evidence, 40)
        entries = [x for x in feature_rows
                   if "research_" in x["hypothesis"] and "research_hold_" not in x["hypothesis"]
                   and "research_reentry_" not in x["hypothesis"] and x["mean_net_bps"] > 0]
        holds = [x for x in feature_rows if "research_hold_" in x["hypothesis"] and x["mean_net_bps"] > 0]
        reentries = [x for x in feature_rows if "research_reentry_" in x["hypothesis"] and x["mean_net_bps"] > 0]
        locals_ = [x for x in _top_hypotheses(result, "/local/", engine.config.min_evidence, 30)
                   if x["mean_net_bps"] > 0]
        exits = [x for x in _top_hypotheses(result, "/exit/", engine.config.min_evidence, 20)
                 if x["mean_net_bps"] > 0]
        for row in entries[:5] + holds[:5] + reentries[:5] + locals_[:5] + exits[:5]:
            universal[row["hypothesis"]] += 1
        all_rows = entries + holds + reentries + locals_ + exits
        enough = any(x["observed_utc_days"] >= engine.config.min_evidence_days for x in all_rows)
        tokens[symbol] = {
            "evidence_status": "PRELIMINARY_MULTI_DAY" if enough else "INSUFFICIENT_DATA",
            "local_candidates": locals_[:8],
            "entry_candidates": entries[:8],
            "hold_candidates": holds[:8],
            "exit_candidates": exits[:8],
            "reentry_candidates": reentries[:8],
            "structure": engine.states[symbol].trend,
            "reentry_ready_count": sum(v for k, v in result["counts"].items() if k.startswith("research_reentry/ready/")),
            "reentry_rejected_count": sum(v for k, v in result["counts"].items() if k.startswith("research_reentry/rejected/")),
            "no_trade_evidence": {
                k.split("research_entry/reason/", 1)[1]: v
                for k, v in result["counts"].items()
                if k.startswith("research_entry/reason/")
            },
            "rule": None if not enough else {
                "LOCAL": "Use only a local hypothesis that survives chronological validation for this token.",
                "STRUCTURE": "Respect validated H1 structure and record continuation hypotheses independently.",
                "FLOW": "Require executed-flow control plus directional price response; volume alone is insufficient.",
                "ENTRY": "Use the highest-evidence causal entry family; never backdate to the local extreme.",
                "HOLD": "Treat isolated counter-flow as noise until evidence supports sustained control transfer.",
                "MFE_EXIT": "Compare MFE recoil jointly with flow weakening, opposite response and structure.",
                "REENTRY": "Require intact structure, observed correction and return of original efficient flow.",
            },
        }
    universal_rows = [{"hypothesis": k, "positive_tokens": n} for k, n in universal.most_common()]
    return {
        "status": status,
        "deployment_ready": False,
        "selection_policy": "Causal descriptive synthesis only; chronological validation and realtime OOS remain mandatory.",
        "tokens": tokens,
        "universal_candidates": universal_rows,
    }


def _previous_hour_snapshot(root, current_ts):
    path = root/"hourly_snapshots.jsonl"
    if not path.is_file():
        return None
    previous = None
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = row.get("ts")
            if _finite(ts) and ts < current_ts:
                previous = row
    return previous


def _count_delta(current, previous, key):
    return current.get(key, 0) - (previous.get(key, 0) if previous else 0)


def render_hourly_report(run_dir, latest=True):
    root = Path(run_dir)
    status_path = root / "research_status.json"
    if not status_path.is_file():
        raise ValueError("research_status.json not found in run directory")
    row = json.loads(status_path.read_text())
    previous = _previous_hour_snapshot(root, row.get("ts", 0))
    lines = [
        f'# CATERPILLAR HOURLY REPORT — {row.get("iso_utc")}',
        "",
        f'Mode: **{row.get("mode")}**. Reason: **{row.get("reason")}**.',
        "",
    ]
    for symbol, token in row.get("tokens", {}).items():
        h1 = token["h1"]
        flow = token.get("recent_flow") or {}
        paper = token["paper"]
        prev_token = (previous or {}).get("tokens", {}).get(symbol, {})
        prev_cov = prev_token.get("data_coverage", {})
        prev_paper = prev_token.get("paper", {})
        delta_trades = token["data_coverage"].get("accepted_trades", 0) - prev_cov.get("accepted_trades", 0)
        delta_blocks = token["data_coverage"].get("flow_blocks", 0) - prev_cov.get("flow_blocks", 0)
        delta_entries = paper["entry_counts"]["accepted"] - prev_paper.get("entry_counts", {}).get("accepted", 0)
        delta_reentries = paper["reentry_counts"]["ready"] - prev_paper.get("reentry_counts", {}).get("ready", 0)
        current_closed = sum(paper["closed_by_model"].values())
        previous_closed = sum(prev_paper.get("closed_by_model", {}).values())
        open_mfe = max((p.get("mfe", 0) for p in paper["open_positions"].values()), default=0)
        open_mae = min((p.get("mae", 0) for p in paper["open_positions"].values()), default=0)
        lines += [
            f"## {symbol}", "",
            f"Structure: **{token.get('structure')}**. Current price: **{token.get('current_price')}**.",
            f"Confirmed Local Low: {json.dumps(h1.get('last_confirmed_low'), ensure_ascii=False)}",
            f"Confirmed Local High: {json.dumps(h1.get('last_confirmed_high'), ensure_ascii=False)}",
            f"Forming local: {json.dumps(h1.get('forming'), ensure_ascii=False)}",
            f"Flow: BUY={flow.get('buy_notional')} SELL={flow.get('sell_notional')} imbalance={flow.get('imbalance')} move_bps={flow.get('move_bps')}.",
            f"Signals: accepted research entries={paper['entry_counts']['accepted']}, rejected={paper['entry_counts']['rejected']}; "
            f"re-entry ready={paper['reentry_counts']['ready']}, rejected={paper['reentry_counts']['rejected']}.",
            f"Open PAPER books: **{len(paper['open_positions'])}**. Current open-book max MFE={open_mfe:.4f} USD; min MAE={open_mae:.4f} USD.",
            f"Since previous hourly snapshot: trades +{delta_trades}, flow blocks +{delta_blocks}, accepted entry hypotheses +{delta_entries}, re-entry-ready +{delta_reentries}, closes +{current_closed-previous_closed}.",
            f"Confidence: **{token['confidence']['status']}**.",
            "",
            "Preliminary findings:",
        ]
        findings = token.get("preliminary_findings") or []
        if findings:
            for item in findings[:5]:
                lines.append(
                    f"- {item['hypothesis']}: n={item['samples']}, mean={item['mean_net_bps']:.3f} bps, "
                    f"positive={item.get('positive_fraction')}"
                )
        else:
            lines.append("- INSUFFICIENT DATA")
        lines.append("")
    lines += [
        "## CHANGES SINCE PREVIOUS HOUR", "",
        ("Previous hourly snapshot: " + str(previous.get("iso_utc")) if previous else "No previous hourly snapshot yet."), "",
        "## CROSS-TOKEN FINDINGS", "",
        json.dumps(row.get("cross_token_findings", []), indent=2, ensure_ascii=False), "",
        "## WHAT IS NOT PROVEN YET", "",
    ]
    for item in row.get("what_is_not_proven_yet", []):
        lines.append("- " + item)
    text = "\n".join(lines) + "\n"
    (root / "HOURLY_REPORT_LATEST.md").write_text(text, encoding="utf-8")
    return text
