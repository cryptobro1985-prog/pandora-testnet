# HYPE D250 — terminal H1 local direction binding audit (2026-11-21 18:32 CET)

Research only. No production changes, no orders, no detector retraining.

## Concrete finding
Inspected existing `d250_raw_m1_preentry_gate_20261121.py` and frozen `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` directly in the designated GitHub branch. The pre-entry gate previously accepted a manifest's LONG/SHORT side without requiring a matching terminal H1 LOW/HIGH type. A mislabeled LONG attached to a HIGH (or SHORT attached to LOW) could pass its price chronology gate if the price bars themselves had no further extension. This is a schema/validation defect, **not** evidence of any bad trade in the historical 67-trade cohort.

## Implemented change
The same pre-entry gate now requires `local_type` in the manifest: LOW for LONG and HIGH for SHORT. Missing/invalid type fails closed via INVALID_INPUT/INVALID_LOCAL_TYPE; mismatch produces LOCAL_SIDE_MISMATCH. Frozen D250 thresholds, entry timing and exit rules remain unchanged. Added five synthetic regression tests for both valid directions, both mismatches and invalid type.

Reproduce from `research/hype_terminal_local_strategy`:
```bash
python -m unittest -v test_d250_local_side_gate_20261121.py
```
Tests are committed but not claimed as CI-verified in this checkpoint.

## Critical limitations
- This validates direction metadata, not the truth of a terminal H1 pivot. Pivot provenance and causal confirmation must be verified separately.
- The 67 individual UTC entry/exit records and matched M1/trade/L50/OI/liquidation/funding tapes were not reconstructed in this iteration. No claim of realized fills, MTM drawdown, liquidation count, MFE retention, or OOS performance.
- The 3x/$531.16 and 5x/$1308.86 figures are historical closed-equity simulation results from the frozen report, not new risk-normalized replay.
- Do not promote rejected MFE overlays without fresh independent forward evidence.

## Next reproducible gate
Produce an immutable 67-trade manifest with `trade_id, local_type, side, local_extreme_utc, h1_confirmed_utc, d250_signal_utc, entry_utc`, source provenance and per-trade UTC bar/tape coverage. Run this updated pre-entry gate first, then perform identical-sample cost-aware event execution replay comparing baseline, 0.25% and 0.5% stop-risk sizing with 1% aggregate stop-risk ceiling, accounting for stops, gaps, mark-price liquidation, funding, fill slippage, monthly equity, MTM/closed DD, and causal MFE exits. Missing data => INDETERMINATE, not success.
