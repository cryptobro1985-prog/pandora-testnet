# HYPE D250 — supplemental mark/liquidation clearance gate (2026-11-21 23:32 CET)

## Scope and provenance
Continuation of frozen D250, no detector retraining, no snapshot classification, no production edits and no real orders. Inspected the existing `d250_conservative_stop_risk_sizer_20261121.py` and `HYPE_D250_RISK_SIZER_MARK_LIQUIDATION_BOUNDARY_AUDIT_2026-11-21_2226_CET.md` directly from the requested GitHub branch. New research-only standalone file: `d250_liquidation_clearance_research_gate_20261121.py`.

## New executable boundary test
The existing sizer accepts 1 bp of clearance beyond stress stop at entry 100, stop 99, assumed liquidation 96.99 (LONG), or stop 101, assumed liquidation 103.01 (SHORT). New gate independently checks:
- explicit authenticated liquidation-state flag and maximum observation age;
- isolated margin and zero other positions (unmodeled cross-margin/portfolio exposure fails closed);
- positive stop and liquidation geometry for both directions;
- assumed stressed stop excursion + explicit clearance + observed entry/mark basis + extra basis uncertainty allowance, strictly below assumed liquidation distance.

For the **illustrative**, not empirically calibrated, settings: 2% gap, 0.5% additional clearance, 0.1% mark-basis uncertainty, 5-second maximum source age, the old near-boundary examples now return BLOCK_CLEARANCE for both sides. Liquidation 95 LONG or 105 SHORT returns PROVISIONAL_CLEARANCE_ONLY if all provenance flags are true. A 0.5% observed entry/mark divergence with liquidation 96.4 LONG also blocks. Nine synthetic tests were executed locally and passed (9/9); GitHub CI not yet verified.

## Interpretation
`PROVISIONAL_CLEARANCE_ONLY` is **not** approval to trade or a no-liquidation guarantee. The source timestamp, margin mode, maintenance tier, mark-price tape, funding and position inventory must be authenticated against actual Bybit account/exchange data. The 0.5% and 0.1% allowances are deliberately exploratory assumptions, not measured historical quantiles. The conservative gate excludes cross margin until portfolio-level liquidation simulation is available; it does not modify the frozen original baseline.

## Still missing
The original UTC 67-trade manifest and matched M1/Public Trades/CVD/L50/liquidations/OI/mark/funding events remain unavailable in this analysis. No matched per-trade fills, monthly net equity, closed or MTM drawdown, stop gap distribution, MFE captured/given back, or independent forward results can be claimed. Next research step: locate the raw archives (including Actions artifacts), reconstruct strictly causal chronological executions and compare unchanged baseline against risk-normalized alternatives on identical samples. Keep previously rejected profit-lock overlays rejected absent independent evidence.
