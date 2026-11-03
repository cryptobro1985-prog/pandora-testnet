"""Append-only evidence and bounded-memory descriptive statistics."""
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import sys

STREAMS = ("trades", "signals", "rejected_signals", "locals", "structure", "flow_events",
           "mfe_analysis", "post_exit", "hypothesis_outcomes", "data_quality", "raw_trades", "candles")


class Metric:
    def __init__(self):
        self.n = 0
        self.mean = self.m2 = 0.0
        self.minimum = self.maximum = None
        self.recent = deque(maxlen=2048)

    def add(self, value):
        if value is None or not math.isfinite(value):
            return
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.recent.append(value)

    def result(self):
        values = sorted(self.recent)
        def quantile(q):
            return values[round((len(values)-1)*q)] if values else None
        return {"count": self.n, "mean": self.mean if self.n else None,
                "std": math.sqrt(max(0, self.m2 / (self.n-1))) if self.n > 1 else None,
                "min": self.minimum, "max": self.maximum,
                "recent_p10": quantile(.1), "recent_median": quantile(.5), "recent_p90": quantile(.9),
                "quantile_scope": "last_2048_observations"}


class Profile:
    def __init__(self):
        self.metrics = {}
        self.counts = {}
        self.outcomes = {}
        self.first = self.last = None

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def add(self, key, value):
        self.metrics.setdefault(key, Metric()).add(value)

    def outcome(self, key, value):
        bucket = self.outcomes.setdefault(key, {"n": 0, "positive": 0, "mean_net_bps": 0.0})
        bucket["n"] += 1
        bucket["positive"] += int(value > 0)
        bucket["mean_net_bps"] += (value-bucket["mean_net_bps"]) / bucket["n"]

    def result(self):
        outcomes = {}
        for key, row in self.outcomes.items():
            n, wins = row["n"], row["positive"]
            p, z = wins/n, 1.96
            center = (p+z*z/(2*n))/(1+z*z/n)
            margin = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
            outcomes[key] = {**row, "positive_fraction": p, "wilson_95": [center-margin, center+margin],
                             "inference_warning": "descriptive only: overlapping labels and serial correlation"}
        for key, row in outcomes.items():
            parts = key.split("/")
            if len(parts) == 4 and parts[1] == "feature":
                baseline = outcomes.get("/".join(parts[:3]+[parts[2]]))
                row["delta_vs_direction_baseline_bps"] = row["mean_net_bps"]-baseline["mean_net_bps"] if baseline else None
        return {"first_event_ts": self.first, "last_event_ts": self.last, "counts": self.counts,
                "metrics": {k: v.result() for k, v in self.metrics.items()}, "hypotheses": outcomes,
                "liquidity_limitation": "Executed turnover and size proxies only; no spread/depth/order-book liquidity measurement."}


class Output:
    def __init__(self, directory, config, symbols, mode, metadata=None):
        self.root = Path(directory)
        # Refuse mixed runs or accidental overwrite. A run has one immutable config.
        self.root.mkdir(parents=True, exist_ok=True)
        if any(self.root.iterdir()):
            raise ValueError("Output directory must be empty: " + str(self.root))
        self.handles = {name: (self.root / (name+".jsonl")).open("w", encoding="utf-8") for name in STREAMS}
        self.meta = {"schema_version": 1, "mode": mode, "symbols": list(symbols), "config": asdict(config),
                     "config_sha256": config.digest, "created_at": datetime.now(timezone.utc).isoformat(),
                     "python": sys.version, "platform": platform.platform(), "metadata": metadata or {},
                     "paper_only": True, "funding": "not included; outputs are net of fees/slippage, before funding",
                     "fill_model": "next eligible public trade plus adverse fixed slippage; unlimited hypothetical liquidity, no queue or market impact",
                     "timestamp_policy": "exchange event time; confirmation/action time distinct from extreme time",
                     "status": "running"}
        self.save_json("run_manifest.json", self.meta)

    def emit(self, stream, row):
        self.handles[stream].write(json.dumps(row, allow_nan=False, separators=(",", ":"))+"\n")

    def flush(self):
        for handle in self.handles.values():
            handle.flush()

    def save_json(self, name, obj):
        path = self.root / name
        tmp = path.with_suffix(path.suffix+".tmp")
        tmp.write_text(json.dumps(obj, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        tmp.replace(path)

    def finish(self, profiles, summary, config, status):
        self.flush()
        self.meta["status"] = status
        self.save_json("run_manifest.json", self.meta)
        self.save_json("token_profiles.json", {s+"_PROFILE": p.result() for s, p in profiles.items()})
        self.save_json("research_summary.json", summary)
        lines = ["# CATERPILLAR RESEARCH REPORT", "", f"Run status: **{status}**. Mode: `{self.meta['mode']}`.",
                 f"Frozen config SHA-256: `{config.digest}`.", "",
                 "Public executed trades only. New extrema are FORMING/UPDATED; confirmation is later and cannot fill at the extreme.",
                 "All PnL is hypothetical USD on independent fixed-notional books, after configured fees and slippage, before funding.",
                 "Alternative exit books are paired counterfactual experiments, not one investable portfolio. End/gap positions are censored, never counted as exits.",
                 "OHLCV fallback supplies closed-bar structure observations only, never BUY/SELL labels, entries or tick-level local claims.",
                 "", "## Data coverage", "", "```json", json.dumps(summary.get("coverage", {}), indent=2), "```", ""]
        for symbol, profile in profiles.items():
            p = profile.result()
            lines += [f"## {symbol}_PROFILE", "", f"Observed trade range: {p['first_event_ts']} – {p['last_event_ts']}.",
                      f"Counts: `{json.dumps(p['counts'], sort_keys=True)}`.", "",
                      "| Research question | Causal hypothesis / evidence |", "|---|---|",
                      "| Local Low / High | Directional excursion, deceleration/absorption, subsequent opposite control; full stage history in locals.jsonl. New lower low alone never confirms. |",
                      "| Structure | Two confirmed highs/lows define trend; event labels record impulse, pullback, exhaustion, absorption, sweeps, breaks and reversal. |",
                      "| LONG / SHORT | Confirmed valid low/high, same-side acceleration, control and price response; opposite absorption veto. Rejected candidates retained. |",
                      "| HOLD | Isolated counterflow stays noise/pullback until sustained transfer or structural failure; all exit predicates are retained. |",
                      "| EXIT / MFE | Compare nine predeclared exit books; MFE recoil requires opposing response and flow, never a standalone trailing stop. |",
                      "| RE-ENTRY | Only after flow exit, intact original local, observed correction and returning control. GOOD/BAD labels use future observations solely for evaluation. |",
                      "| Do not trade | Warmup, stale/gap, invalidated structure, unknown rates, missing flow, inadequate control or absorption. |",
                      "| Large participants | Size/intensity/absorption are observable proxies; no actor identity or market-maker claim. |", "",
                      "### Observed directional / feature outcomes", "",
                      "| Split / hypothesis | N | Positive fraction | Mean net bps |", "|---|---:|---:|---:|"]
            for key, row in sorted(p["hypotheses"].items()):
                lines.append(f"| {key} | {row['n']} | {row['positive_fraction']:.3f} | {row['mean_net_bps']:.3f} |")
            if not p["hypotheses"]:
                lines.append("| No completed outcomes | 0 | — | — |")
            lines += ["", "Exact moment-based metrics and bounded recent quantiles are in token_profiles.json. These are not calibrated trading parameters.", ""]
            ranked = sorted(((k, r) for k, r in p["hypotheses"].items()
                             if k.startswith("evaluation/feature/") and r["n"] >= config.min_evidence
                             and r.get("delta_vs_direction_baseline_bps") is not None),
                            key=lambda item: item[1]["delta_vs_direction_baseline_bps"], reverse=True)
            lines += ["Observed feature lift versus the same-side unconditional baseline (descriptive, correlated samples):", "",
                      "```json", json.dumps([{"hypothesis": k, **r} for k, r in ranked[:10]], indent=2), "```", ""]
        lines += ["## CATERPILLAR 24/7 — evidence gate", "",
                  "The executable model is a frozen research hypothesis: LOCAL → STRUCTURE → FLOW → PRICE RESPONSE → ENTRY → HOLD → MFE → EXIT → RE-ENTRY.",
                  "This run does not automatically establish a profitable or best strategy. The following candidates meet a descriptive sample gate only; independent multi-day walk-forward testing, costs/funding/depth validation and multiple-testing correction remain necessary.", ""]
        candidates = []
        for symbol, p in profiles.items():
            for key, row in p.result()["hypotheses"].items():
                if key.startswith("evaluation/") and row["n"] >= config.min_evidence and row["mean_net_bps"] > 0 and row["wilson_95"][0] > .5:
                    candidates.append({"symbol": symbol, "hypothesis": key, **row})
        lines += ["```json", json.dumps(candidates, indent=2), "```", "",
                  "No automatic parameter fitting or deployment. Empty candidates mean insufficient evidence, not a failed code run.",
                  "Post-exit labels and forward returns are never read by the decision engine. Gap/incomplete horizons are censored."]
        (self.root / "CATERPILLAR_RESEARCH_REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
        self.save_json("caterpillar_24_7_candidates.json", {"deployment_ready": False, "candidates": candidates})
        for handle in self.handles.values():
            handle.close()
