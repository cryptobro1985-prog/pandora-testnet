# HYPE post-local trade risk reconciliation — 2026-11-14 14:33 UTC

Research only. No orders, no production changes, no detector retraining.

## Source files read in this run
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (frozen D250; 71 accepted; 67 fully finalized next-local paths)
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` (67 sequential trades; 22 fixed-cut exits; 0.15% round-trip assumed cost)
- `results/HYPE_EVERY_LOCAL_ROBUST_STRATEGY_2026-11-12.md` (411 sequential trades; distinct population)
- `../hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md` (causal state-transition requirements)
- `trade_manifest_gate_research.py` (schema and limitations)

## New concrete cross-study audit

1. **Do not compare the 67 and 411 trade compounds as paired A/B results.** The 411-trade study explicitly includes Tier B/C/D, uses different entry timing, different stops, and different capital occupancy. It is not the same trade population.
2. **The 67 completed next-local paths are a completed-outcome subset of 71 accepted D250 first signals.** Four accepted signals lack a fully finalized next-opposite-local path in the report. They must be carried as open/censored at evaluation cutoff, not silently removed from mark-to-market equity or forward results.
3. **The published 1% cut is a price move, not 1% account risk.** Published worst modeled equity trade at 5x is -5.75% (1% cut + 0.15% round-trip cost times 5x); at 3x it is -3.45%. The paper does not include a gap allowance or verified mark-to-market DD.
4. **Historical exchange executions cannot be inferred from Public Trades.** No exchange private fill or stop-order lifecycle for these hypothetical trades exists. A historical replay can only produce modeled fills, marked distinctly from actual private fills.
5. **The manifest gate is not a provenance verifier.** It accepts nonempty source strings; `coverage_complete=true` does not prove existence/continuity of L50, Public Trades, OI or mark data, and does not reconstruct stop-order lifecycle.

## New risk-envelope calculation, unchanged entry/exit policy

Exploratory risk sizing for a $100 account, 1% adverse cut, 0.15% total notional costs, and explicitly modeled *additional* stop gap. Notional = equity * risk_fraction / (0.01 + 0.0015 + gap_fraction). The gap is a scenario, not an empirical bound.

| Risk per trade | Additional gap | Maximum modeled notional | Account exposure |
|---|---|---|---|
| 0.25% | 0.00% | $21.74 | 0.2174x |
| 0.50% | 0.00% | $43.48 | 0.4348x |
| 0.25% | 1.00% | $11.63 | 0.1163x |
| 0.50% | 1.00% | $23.26 | 0.2326x |

A 1% structural stop at entry may not be executable with this risk envelope when spread/size/market liquidity are unknown; a structural stop farther than 1% must be sized by its actual distance or the trade vetoed. Both LONG and SHORT require stop-side price validation. Max concurrent planned stop-risk 1% of marked equity; do not reuse occupied margin/capital.

## What was actually run

This run read five existing GitHub research/code files, searched repository code index for trade-level CSV and rich M1 datasets (no matches returned; search indexes only default branch), and calculated the four explicit sizing cases above. **No historical event replay occurred.** This is a new cross-study reconciliation, not evidence of improved PnL.

## Exact next replay gate

1. Locate the chronological 71 D250 signal records, including the four censored/unfinalized cases; keep immutable `signal_available_ts`, direction and original anchor.
2. Locate timestamp-indexed M1 trade/mark, L50, liquidation and OI archives and verify actual availability at each signal and through exit; missing rich data is UNKNOWN, never zero.
3. For each candidate build one ordered stream: signal availability -> modeled order submission -> conservative executable fill -> stop placement/ack -> minute/tick mark -> stop trigger/market fill OR causal opposite-local signal -> exit fill. Public prints do not count as private executions.
4. Replay original 1% adverse cut / hold-to-opposite unchanged against 0.25% and 0.5% risk-budget sizing, staged entry, and predeclared protective alternatives on identical chronological signals. Rejected MFE overlays remain rejected until independent forward evidence.
5. Calculate monthly net equity, open-position MTM drawdown, closed drawdown, censored end-of-sample MTM, cost/slippage/funding, MFE captured/given back, stop gap, fills, liquidation buffer and observed modeled liquidations; distinguish unavailable fields.
6. Never claim independent forward results from the already inspected May–Nov history.

## Conclusion
Current defensible output is a stricter risk envelope and a four-signal censoring warning. No verified safe profitable live strategy, zero-liquidation guarantee or improved MFE retention is established.
