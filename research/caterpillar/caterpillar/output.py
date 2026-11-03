"""Append-only evidence and bounded-memory descriptive statistics."""
from collections import OrderedDict, deque
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

from . import __version__

STREAMS = ("trades", "signals", "rejected_signals", "locals", "structure", "flow_events",
           "mfe_analysis", "post_exit", "hypothesis_outcomes", "data_quality", "raw_trades", "candles")


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def running_mean(mean, value, n):
    # Avoid value-mean overflow when both finite inputs have opposite signs.
    return mean + (value-mean)/n if math.isfinite(value-mean) else mean*((n-1)/n)+value/n


def finite_total(metric):
    total = metric.mean*metric.n if metric and metric.n else None
    return total if total is not None and math.isfinite(total) else None


def safe_median(values):
    if not values:
        return None
    values = sorted(values)
    middle = len(values)//2
    return values[middle] if len(values) % 2 else running_mean(values[middle-1], values[middle], 2)


def package_source_sha256():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode()+b"\0")
        digest.update(path.read_bytes()+b"\0")
    return digest.hexdigest()


class Metric:
    def __init__(self):
        self.n = 0
        self.mean = self.m2 = 0.0
        self.minimum = self.maximum = None
        self.recent = deque(maxlen=2048)

    def add(self, value):
        if not finite_number(value):
            return False
        self.n += 1
        delta = value - self.mean
        self.mean = running_mean(self.mean, value, self.n)
        self.m2 += delta * (value - self.mean)
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.recent.append(value)
        return True

    def result(self):
        values = sorted(self.recent)
        def quantile(q):
            return values[round((len(values)-1)*q)] if values else None
        return {"count": self.n, "mean": self.mean if self.n else None,
                "std": math.sqrt(max(0, self.m2 / (self.n-1))) if self.n > 1 and math.isfinite(self.m2) else None,
                "std_status": "available" if self.n > 1 and math.isfinite(self.m2) else "insufficient_samples" if self.n < 2 else "numeric_overflow",
                "min": self.minimum, "max": self.maximum,
                "recent_p10": quantile(.1), "recent_median": quantile(.5), "recent_p90": quantile(.9),
                "quantile_scope": "last_2048_observations"}


class Profile:
    def __init__(self):
        self.metrics = {}
        self.counts = {}
        self.outcomes = {}
        self.daily = {}
        self.evicted_days = {}
        self.first = self.last = None

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def add(self, key, value):
        self.metrics.setdefault(key, Metric()).add(value)

    def outcome(self, key, value, ts=None):
        if not finite_number(value):
            self.count("quality/nonfinite_outcome")
            return False
        bucket = self.outcomes.setdefault(key, {"n": 0, "positive": 0, "mean_net_bps": 0.0})
        bucket["n"] += 1
        bucket["positive"] += int(value > 0)
        bucket["mean_net_bps"] = running_mean(bucket["mean_net_bps"], value, bucket["n"])
        if ts is not None:
            try:
                if not finite_number(ts):
                    raise ValueError("nonfinite timestamp")
                day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
            except (ValueError, OverflowError, OSError):
                self.count("quality/invalid_outcome_timestamp")
            else:
                days = self.daily.setdefault(key, OrderedDict())
                if day not in days:
                    days[day] = {"n": 0, "positive": 0, "mean_net_bps": 0.0}
                daily = days[day]
                daily["n"] += 1
                daily["positive"] += int(value > 0)
                daily["mean_net_bps"] = running_mean(daily["mean_net_bps"], value, daily["n"])
                # Bounded by calendar days, never by the number of tick outcomes.
                if len(days) > 128:
                    days.popitem(last=False)
                    self.evicted_days[key] = self.evicted_days.get(key, 0)+1
        return True

    def result(self):
        outcomes = {}
        for key, row in self.outcomes.items():
            n, wins = row["n"], row["positive"]
            p, z = wins/n, 1.96
            center = (p+z*z/(2*n))/(1+z*z/n)
            margin = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
            days = self.daily.get(key, {})
            daily_means = [d["mean_net_bps"] for d in days.values()]
            temporal_n = sum(d["n"] for d in days.values())
            outcomes[key] = {**row, "positive_fraction": p,
                             "wilson_95_iid_reference_only": [center-margin, center+margin],
                             "daily_observations": dict(days), "observed_utc_days": len(days),
                             "timestamped_samples_retained": temporal_n,
                             "daily_mean_median_net_bps": safe_median(daily_means),
                             "positive_day_fraction": sum(x > 0 for x in daily_means)/len(days) if days else None,
                             "daily_scope": "up_to_128_UTC_days; per-day means are descriptive, not independent samples",
                             "evicted_daily_buckets": self.evicted_days.get(key, 0),
                             "inference_warning": "No significance claim: overlapping horizons, serial correlation and multiple comparisons. IID Wilson reference is not used to select candidates."}
        for key, row in outcomes.items():
            parts = key.split("/")
            if len(parts) == 4 and parts[1] == "feature":
                baseline = outcomes.get("/".join(parts[:3]+[parts[2]]))
                delta = row["mean_net_bps"]-baseline["mean_net_bps"] if baseline else None
                row["delta_vs_direction_baseline_bps"] = delta if finite_number(delta) else None
                row["baseline_samples"] = baseline["n"] if baseline else None
                row["baseline_scope"] = "same-side unconditional block outcomes; feature subset is included in baseline"
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
        # A simultaneous second process can pass the emptiness check above. An
        # exclusive claim prevents two writers from mixing/truncating one run.
        try:
            with (self.root/".run.lock").open("x"):
                pass
        except FileExistsError:
            raise ValueError("Output directory is already claimed: " + str(self.root)) from None
        self.handles = {}
        try:
            for name in STREAMS:
                self.handles[name] = (self.root / (name+".jsonl")).open("w", encoding="utf-8")
        except Exception:
            for handle in self.handles.values():
                handle.close()
            raise
        self.meta = {"schema_version": 2, "mode": mode, "symbols": list(symbols), "config": asdict(config),
                     "config_sha256": config.digest, "created_at": datetime.now(timezone.utc).isoformat(),
                     "package_version": __version__, "package_source_sha256": package_source_sha256(),
                     "python": sys.version, "platform": platform.platform(), "metadata": metadata or {},
                     "local_timeframe": "1h", "paper_only": True, "funding": "not included; outputs are net of fees/slippage, before funding",
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
        try:
            self._finish(profiles, summary, config, status)
        finally:
            for handle in self.handles.values():
                handle.close()

    def _finish(self, profiles, summary, config, status):
        self.flush()
        self.meta["status"] = "finalizing"
        self.save_json("run_manifest.json", self.meta)
        self.save_json("token_profiles.json", {s+"_PROFILE": p.result() for s, p in profiles.items()})
        self.save_json("research_summary.json", summary)
        lines = ["# CATERPILLAR RESEARCH REPORT", "", f"Run status: **{status}**. Mode: `{self.meta['mode']}`.",
                 f"Frozen config SHA-256: `{config.digest}`.", "",
                 "Public executed trades only. Local High/Low are derived exclusively from hourly candles. Forming H1 extrema cannot confirm before a later H1 closes; no fill is backdated to the extreme.",
                 "All PnL is hypothetical USD on independent fixed-notional books, after configured fees and slippage, before funding.",
                 "Alternative exit books are independent counterfactual experiments with different entry/re-entry times, not paired trials or one investable portfolio. End/gap positions are censored, never counted as exits.",
                 "OHLCV fallback supplies closed-bar structure observations only, never BUY/SELL labels, entries or tick-level local claims.",
                 "", "## Data coverage", "", "```json", json.dumps(summary.get("coverage", {}), indent=2), "```", ""]
        for symbol, profile in profiles.items():
            p = profile.result()
            lines += [f"## {symbol}_PROFILE", "", f"Observed trade range: {p['first_event_ts']} – {p['last_event_ts']}.",
                      f"Counts: `{json.dumps(p['counts'], sort_keys=True)}`.", "",
                      "| Research question | Causal hypothesis / evidence |", "|---|---|",
                      "| Local Low / High | H1 extreme versus prior closed H1 context, then confirmation by a subsequent closed H1; full stage history in locals.jsonl. Flow blocks never create confirmed locals. |",
                      "| Structure | Two confirmed highs/lows define trend; event labels record impulse, pullback, exhaustion, absorption, sweeps, breaks and reversal. |",
                      "| LONG / SHORT | Confirmed valid low/high, same-side acceleration, control and price response; own-side absorption veto. Rejected candidates retained. |",
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
            lines += ["", "### Exit-book comparison after configured costs, before funding", "",
                      "Closed-only summaries below exclude censored and still-open positions; compare those counts before interpreting returns. Different books can enter at different times, so this is a descriptive comparison, not a paired estimate of exit quality.", "",
                      "| Exit model | Closed | Censored | Still open | Net USD sum | Net USD / close | Mean MFE USD | Mean MAE USD |",
                      "|---|---:|---:|---:|---:|---:|---:|---:|"]
            books = summary.get("open_books_not_realized", {}).get(symbol, {})
            for model in config.exit_models:
                net = profile.metrics.get(model+"/net_usd")
                mfe = profile.metrics.get(model+"/mfe")
                mae = profile.metrics.get(model+"/mae")
                def number(value):
                    return f"{value:.4f}" if finite_number(value) else "—"
                lines.append(f"| {model} | {p['counts'].get(model+'/closed', 0)} | {p['counts'].get(model+'/censored', 0)} | {int(bool(books.get(model, {}).get('position')))} | {number(finite_total(net))} | {number(net.mean if net and net.n else None)} | {number(mfe.mean if mfe and mfe.n else None)} | {number(mae.mean if mae and mae.n else None)} |")
            lines += ["", "Exact moment-based metrics and bounded recent quantiles are in token_profiles.json. These are not calibrated trading parameters.", ""]
            ranked = sorted(((k, r) for k, r in p["hypotheses"].items()
                             if k.startswith("evaluation/feature/") and r["n"] >= config.min_evidence
                             and r.get("delta_vs_direction_baseline_bps") is not None),
                            key=lambda item: item[1]["delta_vs_direction_baseline_bps"], reverse=True)
            lines += ["Observed feature lift versus the same-side unconditional baseline (descriptive, correlated samples):", "",
                      "```json", json.dumps([{"hypothesis": k, **r} for k, r in ranked[:10]], indent=2), "```", ""]
        lines += ["## CATERPILLAR 24/7 — evidence gate", "",
                  "The executable model is a frozen research hypothesis: LOCAL → STRUCTURE → FLOW → PRICE RESPONSE → ENTRY → HOLD → MFE → EXIT → RE-ENTRY.",
                  "This run does not establish a profitable or best strategy. The following items are exploratory review candidates only. The descriptive gate requires a completed run, filled entry/re-entry or realized exit hypotheses, timestamped evaluation observations on multiple UTC days, positive overall mean and positive median daily mean. Unfilled entry signals cannot qualify. It never uses an IID significance test. Independent multi-day walk-forward testing, costs/funding/depth validation and multiple-testing correction remain necessary.", ""]
        candidates = []
        for symbol, p in profiles.items():
            for key, row in p.result()["hypotheses"].items():
                parts = key.split("/")
                eligible_hypothesis = (len(parts) == 4 and parts[0] == "evaluation" and
                                      (parts[1] == "exit" or parts[1] == "feature" and parts[3].startswith(("filled_open_", "filled_reentry_"))))
                temporal_complete = row["timestamped_samples_retained"] == row["n"] and row["evicted_daily_buckets"] == 0
                if (status == "completed" and eligible_hypothesis and row["n"] >= config.min_evidence
                        and temporal_complete and row["observed_utc_days"] >= config.min_evidence_days
                        and row["mean_net_bps"] > 0 and row["daily_mean_median_net_bps"] > 0):
                    candidates.append({"symbol": symbol, "hypothesis": key, "evidence_status": "exploratory_only", **row})
        lines += ["```json", json.dumps(candidates, indent=2), "```", "",
                  "No automatic parameter fitting or deployment. Empty candidates mean insufficient evidence, not a failed code run.",
                  "Post-exit labels and forward returns are never read by the decision engine. Gap/incomplete horizons are censored."]
        (self.root / "CATERPILLAR_RESEARCH_REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
        self.save_json("caterpillar_24_7_candidates.json", {"deployment_ready": False,
                       "selection_policy": "descriptive multi-day evaluation review; no optimality or significance claim",
                       "suppressed_due_to_run_status": status != "completed", "candidates": candidates})
        self.meta["status"] = status
        self.save_json("run_manifest.json", self.meta)
