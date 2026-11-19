# HYPE D250 — entry-to-stop geometry and risk-budget consistency audit
Date: 2026-11-19 19:33 CET. Research only; no orders, detector retraining, or production changes.

## Source provenance
Read the frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, and entry_execution_manifest_gate_20261119.py on this branch. All numerical results below are exact algebra from those reports, NOT a matched Bybit execution replay.

## New consistency finding
The frozen D250 entry requires a side-normalized reversal >2.084004943 H1 ATR, after 250 minutes without same-side invalidation. Its *diagnostic structural* stop is 0.25 H1 ATR beyond the original extreme, giving an entry-to-structural-stop distance strictly >2.334004943 H1 ATR (before execution costs), conditional on the original local and ATR reference being unchanged. The source reports a median structural price risk of 3.140%. The separate 1.0% entry-price adverse cut is therefore a substantially different exit mechanism; it does not represent a structural stop. In particular, a 1% cut may close a valid post-local trend before structural invalidation, and it was selected on development data, not proved universally safe.

## Cost-aware risk algebra
Let E be equity, r in [0.0025,0.005], N entry notional, d adverse-price stop distance as a fraction of entry, f_entry/f_exit the fee fractions, and g the *additional adverse fill gap* fraction. Approximate worst modeled loss is N*(d+g+f_entry+f_exit), assuming linear USDT perpetual, no funding, and small price moves. Hence N <= E*r/(d+g+f_entry+f_exit), also capped by account-wide open stop risk <= 1% E and margin/exchange constraints. Actual losses may exceed this when g is exceeded; not a guarantee.

At E=$100, d=0.01, assumed round-trip f=0.0015 (the frozen report's *assumption*, not verified Bybit actual fees):
- r=0.005, g=0: N=$43.4783, gross exposure=0.4348x equity.
- r=0.005, g=0.005: N=$30.3030, gross exposure=0.3030x equity.
- r=0.005, g=0.02: N=$15.8730, gross exposure=0.1587x equity.
- r=0.0025, g=0.02: N=$7.9365, gross exposure=0.0794x equity.
The original 3x/5x *account exposure* histories are therefore not comparable to a 0.25%-0.5% stop-risk sizing regime. Rescaling terminal compound without replay is invalid.

## Critical replay audit gap discovered in current manifest gate
The gate only checks aggregate quote/mark/L50 event counts, max gaps, and mark_min/max; it does not prove a timestamp-ordered price path, stop-trigger provenance, fill depth, event sequencing, funding times, or account-level capital allocation. It also does not reject NaN in every numeric field (Python comparisons against NaN can silently return false). Therefore a gate PASS must never be described as execution-replay validation. This is an audit finding, not an executed 67-trade replay.

## Exact next data work, no synthetic substitute
1. Locate original 67 per-trade UTC records, each with frozen local confirmation and D250 signal timestamp; preserve source SHA and chronological sample IDs. Distinguish them from 71 accepted signals and 411 trades.
2. Join each trade to timestamped Bybit trades/CVD, bid/ask and L50 depth, mark-price, liquidations, OI and funding; report missing streams as unknown, never impute zero.
3. Replay original unchanged 1% cut + opposite K2 exit, then 0.25/0.5% risk sizing, staged entry, mandatory stop and separately labeled experimental MFE exits on *identical* event windows. Separate LOW/LONG and HIGH/SHORT.
4. Track stop trigger source and execution fill separately; calculate liquidation precedence from mark price and actual margin tier. Mark unresolved intervals UNKNOWN rather than zero liquidations.
5. Calculate net monthly equity, closed and mark-to-market drawdown, funding/fees/slippage, MFE retention, stop and partial-fill counts, and independent unseen forward. Reject any overlay lacking improvement across independent forward.

## Status
No historical fill replay or independent forward was executed in this checkpoint; no new PnL, DD, or liquidation claims. Frozen thresholds unchanged. The 61.2% median MFE giveback and late-Aug negative causal exit performance remain unresolved. Existing rejected MFE/flow and ATR trail overlays stay rejected.
