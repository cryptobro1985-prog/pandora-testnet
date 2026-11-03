# Caterpillar Research v2 — runbook

This directory is an isolated **PAPER / RESEARCH ONLY** system. It does not import production PANDORA, has no order endpoint, and must not be given private trading keys.

## Fixed universe

Only these ten linear USDT perpetual symbols are allowed:

- ZEC
- HYPE
- NEAR
- SOL
- ENA
- 1000PEPE
- DOGE
- SUI
- AAVE
- WLD

There is no Top-5/Top-10 rotation and missing symbols are not replaced.

## What v2 researches

The engine keeps the original causal H1/PAPER implementation and adds a parallel research layer:

- competing causal H1 Local High/Low hypotheses (different lookbacks/retreat requirements);
- flow evidence attached to local confirmation, including dominant-flow deceleration, absorption, failed price impact and opposite-side price response;
- independent LONG and SHORT research hypotheses on every completed flow block, including from-local and trend-continuation cases;
- executed BUY/SELL notional, counts, intensity, acceleration/deceleration, large-trade anomalies and price efficiency;
- optional public L1 best bid/ask, spread/top-size imbalance and public liquidation context;
- tick-by-tick PAPER MFE/MAE plus multiple exit predicates;
- richer re-entry observations: correction depth/duration, intact local/structure, returning control, acceleration and absorption;
- hourly snapshots, a latest status file and a human-readable hourly report;
- crash checkpoints and resume for historical and realtime collection;
- conservative per-token strategy synthesis. Insufficient evidence remains `INSUFFICIENT_DATA`.

The research layer does **not** claim to identify a particular market maker. It records only observable large-participant-like patterns.

## Install and verify

```bash
cd research/caterpillar
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q caterpillar scripts tests
.venv/bin/python -m unittest discover -s tests -v
```

GitHub CI for this branch runs the same checks in `.github/workflows/caterpillar-research-ci.yml`.

## Persistent output is mandatory for long runs

The output directory contains the evidence, checkpoints and hourly snapshots. For a 30-day historical run or a 6-hour realtime run, point `--output` and `--cache` at storage that survives process/container restarts.

Do **not** rely on an ephemeral container filesystem and then claim crash persistence. The checkpoint implementation makes a run restartable only if the output/cache files themselves survive the restart.

A resume requires the same research source hash and frozen config. This intentionally prevents continuing an old checkpoint under silently changed code.

## 30-day historical research

Example with an explicit chronological discovery/evaluation split:

```bash
.venv/bin/python -m caterpillar historical_research \
  --days 30 \
  --split-date 2026-10-20 \
  --cache /persistent/caterpillar/cache \
  --output /persistent/caterpillar/runs/history-30d-001
```

Or use exact dates:

```bash
.venv/bin/python -m caterpillar historical_research \
  --start-date 2026-10-01 \
  --end-date 2026-11-01 \
  --split-date 2026-10-22 \
  --cache /persistent/caterpillar/cache \
  --output /persistent/caterpillar/runs/history-202610
```

Historical executed trades are read chronologically and streamed one symbol/day at a time. Missing trade archives are recorded as incomplete coverage; OHLCV fallback may supply H1 structure only and is never converted into synthetic BUY/SELL flow.

### Historical resume

Use the same output and cache:

```bash
.venv/bin/python -m caterpillar historical_research \
  --resume \
  --cache /persistent/caterpillar/cache \
  --output /persistent/caterpillar/runs/history-30d-001
```

Without new date flags, resume restores the original frozen date range from the manifest. Completed symbol/day segments are not processed again. Mid-segment evidence is restored from the last atomic checkpoint and append-only streams are truncated to that checkpoint before continuation.

## Realtime six-hour OOS audit

```bash
.venv/bin/python -m caterpillar realtime_audit \
  --hours 6 \
  --record-trades \
  --market-context \
  --output /persistent/caterpillar/runs/realtime-oos-001
```

The realtime run is treated as evaluation from its first observation. `--market-context` adds research-only L1 spread/top-size and liquidation observations; it does not turn them into mandatory trading filters.

### Realtime resume

```bash
.venv/bin/python -m caterpillar realtime_audit \
  --resume \
  --output /persistent/caterpillar/runs/realtime-oos-001
```

A process restart creates an explicit continuity gap. Open research positions are censored rather than pretending missed trades did not exist. Past evidence, MFE/MAE history, locals, profiles and progress remain in the run.

## Hourly update

The engine continuously rewrites:

- `research_status.json` — latest machine-readable state;
- `hourly_snapshots.jsonl` — append-only hourly states.

Render a human-readable latest report at any time:

```bash
.venv/bin/python -m caterpillar hourly_report \
  --latest \
  --output /persistent/caterpillar/runs/realtime-oos-001
```

This writes `HOURLY_REPORT_LATEST.md` and prints it. The report includes every token's H1 locals, forming research locals, structure, recent flow, entry/re-entry research counts, open PAPER books, MFE/MAE, preliminary findings, data quality and changes since the previous hourly snapshot.

## Evidence streams

The run writes append-only evidence including:

- `trades.jsonl`
- `signals.jsonl`
- `rejected_signals.jsonl`
- `locals.jsonl`
- `local_hypotheses.jsonl`
- `entry_hypotheses.jsonl`
- `structure.jsonl`
- `flow_events.jsonl`
- `price_response.jsonl`
- `large_participant_events.jsonl`
- `market_context.jsonl`
- `positions.jsonl`
- `mfe_analysis.jsonl`
- `exit_hypotheses.jsonl`
- `reentry_hypotheses.jsonl`
- `post_exit.jsonl`
- `hypothesis_outcomes.jsonl`
- `data_quality.jsonl`
- `raw_trades.jsonl` when requested
- `hourly_snapshots.jsonl`

State/report files include:

- `checkpoint.json`
- `historical_progress.json` for historical mode
- `research_status.json`
- `token_profiles.json`
- `research_summary.json`
- `strategy_synthesis.json`
- `CATERPILLAR_RESEARCH_REPORT.md`
- `HOURLY_REPORT_LATEST.md` after hourly-report generation

## Local research

The production-neutral research layer currently compares predeclared causal variants rather than fitting an unlimited parameter grid after seeing returns. A candidate is formed only from closed H1 information and cannot be confirmed on its own extreme hour. Confirmation/outcome times are kept separate from the H1 extreme.

At confirmation, causal flow evidence is attached as research tags, not gates. This allows the historical run to ask whether an H1 structural retreat works better when it coincides with seller/buyer exhaustion, absorption, failed impact, large-trade context or efficient opposite-side price response.

The fixed/core H1 model remains present as a control hypothesis. Research results must not silently mutate that control during the same evaluation run.

## Entry research

Every flow block evaluates both LONG and SHORT research families independently. A rejected side is still recorded with reasons. This prevents a recent Local Low from hiding a valid SHORT-continuation hypothesis (and vice versa).

Predeclared conjunctions such as control + acceleration, local + control + acceleration, and trend + control + acceleration are measured prospectively. The engine does not enumerate arbitrary combinations after seeing PnL.

## MFE / exit / re-entry

PAPER MFE/MAE are updated on every accepted trade. Multiple exit books remain independent experiments. Exit hypotheses retain flow weakening, opposite control, price reversal, absorption, MFE recoil and structure/local invalidation evidence.

Re-entry research logs correction depth/duration, original local integrity, structure, original/opposite control, acceleration and absorption. A later label is research evidence only; it cannot feed backward into the decision.

## Interpretation rules

A six-hour run is useful for transport verification and short-term observations, but it is not enough to declare an ideal 24/7 strategy. Multi-day historical discovery must be separated chronologically from validation, followed by a frozen realtime OOS run.

Never promote a rule because of a single large winner. Report sample size, coverage, time span and negative evidence. If the minimum evidence gate is not met, retain `INSUFFICIENT_DATA`.

Funding, queue position, full market impact and actor identity are not proven by this research model. Public L1/order-flow context is observational evidence, not proof that a specific market maker acted.
