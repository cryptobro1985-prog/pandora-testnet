# Frozen D250 trade-level replay gate — 2026-11-17 02:27 CET

Research only. No detector retraining, no real orders, no production changes.

## New concrete work
Read the original frozen D250 report, asymmetric-risk report, and 01:30 cost-fragility checkpoint from this exact branch. Added executable `research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py` to prevent aggregate historical performance from being represented as matched per-trade replay.

The script accepts an immutable trade manifest CSV and produces per-trade eligibility / reason-coded rejection JSON. It rejects missing timestamps, side/local mismatches, pre-D250 signals, pre-H1-confirmation entries, features timestamped after the signal, frozen threshold failures, absent public trades/M1/mark coverage, duplicates and incomplete exit chronology. It separately counts LOW→LONG and HIGH→SHORT. It does NOT invent missing features.

## Reproducible invocation
```bash
python research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py \
  path/to/real_67_trade_manifest.csv --out path/to/d250_manifest_gate.json
```

The script deliberately does not ship a synthetic manifest as evidence and does not claim any exchange fill. It is a prerequisite, **not** a substitute, for a matched event replay. Coverage COMPLETE remains an unverified manifest assertion until independently cross-checked with timestamped exchange archives.

## New source-level risk finding
The 2026-11-12 asymmetric-risk report states '1.00% below/above entry, unless an existing structural stop is closer'. Consequently the purported 1% adverse-price cut is a *maximum intended distance*, not necessarily a uniform realized stop distance. The reported worst modeled 5x trade of -5.75% is exactly 5 × (1.00% + 0.15%) under the ideal no-gap cost model, but does not prove that every position had a 1% stop or that a stop was filled at its trigger. Before applying risk-based sizing, the individual effective stop price must be reconstructed for every trade, and actual slippage/gap/mark-price liquidation precedence must be separately evaluated.

## Results / limits
- Original D250: 71 accepted episodes, 67 with finalized opposite local; these are not 67 verified exchange fills.
- Original 67 paper trades: 22 fixed-cut exits; no matched individual execution ledger was available in the three inspected reports.
- New gate code saved; **no 67-trade event replay executed in this iteration**, no new net PnL, MTM drawdown, monthly equity, stop fills, MFE capture, liquidation count or independent forward return.
- No thresholds changed; previously rejected MFE overlays remain rejected.

## Next action
Recover immutable per-trade UTC IDs and event-level source references from existing historical artifacts, then generate a manifest and run this gate. Match actual event tapes before calculating fills, stop gaps, cost-aware sizing (0.25–0.5% equity risk, 1% aggregate stop risk), liquidation and MFE protection, comparing identical trades chronologically without capital overlap. If required source data is absent, preserve UNKNOWN rather than extrapolating.
