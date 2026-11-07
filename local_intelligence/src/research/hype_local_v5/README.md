# HYPE causal local research: reproducible runner

Research only. No orders, production imports, deploy, or live trading changes.
Use the existing checkout on `research/hype-h1-local-v5-oi-microstructure-20261104`.

## Current evidence

Read [RESULTS.md](RESULTS.md) before interpreting any score. The real 30-day
study is blocked by the running environment's outbound network policy. Tests
and synthetic integration replay verify software contracts, not market precision.

## Install and test

From `/workspace/pandora-testnet` (Python 3.12):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r research/hype_local_v5/requirements-research.txt
.venv/bin/python -m unittest discover -s research/hype_local_v5/tests -v
```

## Acquire real inputs

```bash
.venv/bin/python research/hype_local_v5/acquire.py --fetch --output /workspace/hype-data
```

Uses existing proxy/CA/authentication. Failed or partial acquisition exits 2 and
records exact errors; it never creates substitute market data. Artifact IDs and
expected names are built in. A Git read capability does not establish Actions API
authorization. Five-minute REST OI does not provide 30-second historical OI.
The old `TICKS-*` artifacts are **minute flow aggregates**, not retained raw trades.

The historical artifact-retrieval method is preserved in commit `b76aa569`:
GitHub Actions runs `gh api /repos/OWNER/REPO/actions/artifacts/ID/zip` with its
existing `github.token` and `actions: read` permission. Use this source independently:

```bash
.venv/bin/python research/hype_local_v5/acquire.py --fetch --source artifacts \
  --artifact-ids 13278474318 --output /workspace/hype-recovered
```

Private artifact preflight now also uses authenticated `gh api`; an anonymous
HTTP 404 cannot suppress a download authorized for the runner. No Bybit request
is made in artifact-only mode. The manually triggered
`.github/workflows/hype-local-v5-artifact-recovery.yml` implements that previous
Actions route, recovers requested artifacts, preserves partial evidence and runs
discovery if the original minute archive is available. It never evaluates final
OOS or places orders. The new workflow has been prepared locally, **not dispatched**.
It does not change or bypass the cloud machine's network policy.

Canonical bar fields: `start_ms`, `bar_end_ms`, `ts_ms` (availability),
`interval_ms`, OHLC, nullable buy/sell notional. Universal `ts` is Unix seconds;
the reader converts modern epoch seconds, while explicit `*_ms` stays milliseconds.
Minute highs/lows have time **intervals**, never invented within-minute times.
Overlaps/conflicts, malformed prices, reordered data and future availability fail.
Missing intervals stay gaps and force the detector to warm up again.

Convert downloaded actual daily raw trades to 5-second bars:

```bash
.venv/bin/python -m research.hype_local_v5.pipeline prepare-raw \
  --raw /workspace/hype-data/raw/HYPEUSDT*.csv.gz \
  --raw-end 2026-11-03 --interval-ms 5000 --output /workspace/hype-data/bars5s
```

`--raw-end` is an exclusive UTC archive-completeness contract. No executions
are invented for empty buckets. `raw_bars.csv` can then be supplied as `--bars`.
Aggregation preserves actual raw row order for open/close but does not claim
that a 5-second OHLC bar retains every within-bar execution.

## Discovery and sealed final OOS

```bash
.venv/bin/python -m research.hype_local_v5.pipeline discover \
  --bars /workspace/hype-data/artifacts/universal-minute-HYPE/HYPE_minutes.csv.gz \
  --output /workspace/hype-study

.venv/bin/python -m research.hype_local_v5.pipeline evaluate-oos \
  --bars /workspace/hype-data/artifacts/universal-minute-HYPE/HYPE_minutes.csv.gz \
  --selection /workspace/hype-study/selection.json --output /workspace/hype-study
```

Use `--interval-ms 5000` for actual 5-second bars. Optional `--oi <CSV>` joins
historical OI causally. Unless historical receipt times exist, publication time is
explicitly **assumed** sample+300 seconds (`--oi-publication-lag-ms`); this is a
sensitivity assumption, not proof of historical observability. Five-minute OI
never supplies 30/60/180-second changes. Optional `--snapshots <JSONL>` joins
forward observations as of receipt with bounded age. Use identical files/options
in discovery and final OOS; source hashes and parsing configuration are sealed.

Windows are UTC, half-open: warmup 4–11 October; discovery 11–27 October;
OOS 27 October–3 November 2026. Two chronological discovery folds end on
23 and 27 October; fold reference labels and machine state are recomputed on
their own prefixes. The final two hours are excluded from scoring to support
K2 labels, and unlabelable intervals are censored explicitly. >=99% observed
coverage and actual start/end support are required before market evaluation.

The small predeclared grid compares four maturity/score configurations per A–F
family. A is structure-only. B adds executed flow; C adds OI; D adds OI/liquidations;
E adds OI/book; F uses all blocks. B–F require observed climax→absorption→effective
transfer. Missing inputs cause WAIT, never artificial zero values. Models without
decisions in both folds are ineligible. Selection uses the Wilson precision lower
bound and reports recall/delay alongside it; it does not guarantee useful coverage.

`OOS_CONSUMED_<selection hash>.json` is written beside the selection **before**
evaluation. Changing output directories cannot repeat the same sealed evaluation.
Failed evaluations remain consumed. Code hashes, data hashes, intervals and OI lag
are checked. Do not make another study or tune thresholds after viewing final OOS.

Output CSV/JSON ledgers include candidates, immutable confirmed locals, swing
episodes, score trajectories, machine-episode acceptances, first accepted signal
per reference swing, false/missed locals and censored events. The first false
signal cannot be erased by a later successful signal inside the same true swing.
The offline reference never resets or initializes the live machine.

## Forward research

```bash
.venv/bin/python research/hype_local_v5/research.py --mode live \
  --minutes 20 --output /workspace/hype-forward
.venv/bin/python -m research.hype_local_v5.pipeline forward \
  --bars /workspace/hype-data/bars5s/raw_bars.csv --interval-ms 5000 \
  --snapshots /workspace/hype-forward/HYPE_live_microstructure_1s.jsonl \
  --family F --output /workspace/hype-forward-replay
```

The collector now saves exact incoming raw frames and receipt sequence, OI
refresh timestamps, ACK-based observed coverage and book freshness/sequence.
`data.replay_raw_frames(path)` replays those envelopes on their receipt clock.
Raw frames can be converted to snapshot JSONL by iterating this function; this
does not synthesize history. Historical price bars and forward snapshots must
actually overlap; otherwise required observations remain missing.

Book additions/aggressive-flow ratios are explicitly marked **proxies**, not
proof of true depth consumed/restored or position attribution. Old artifacts
without timestamps/coverage cannot be silently upgraded. Twenty minutes alone
cannot warm up six H1 hours or validate enough structural reversals.

The engine uses a transparent smoothed evidence score, **not** a calibrated
probability, fitted likelihood ratio, Bayesian posterior, or SPRT. Fitting a proper
sequential likelihood and recommending market thresholds remain contingent on
real discovery data and untouched OOS evidence. Never interpret score .8 as 80%.
