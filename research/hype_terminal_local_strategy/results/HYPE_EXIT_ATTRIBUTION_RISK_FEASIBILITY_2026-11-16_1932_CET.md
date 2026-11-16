# HYPE D250 — exit attribution and stop-risk feasibility checkpoint (2026-11-16 19:32 CET)

Research only. Frozen entry and rejected overlays unchanged. No private fills, mark-price replay or production changes.

## Verified source documents
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `results/HYPE_67_TRADE_OUTCOME_RECONCILIATION_2026-11-16_1830_CET.md`
- `m1_stop_order_ambiguity_replay_20261116.py`
- `trade_manifest_gate_research.py`

## New cross-study reconciliation
The 67 D250 entries with finalized future opposite local have **67/67 positive gross excursion to the FUTURE exact extreme**, an oracle-only geometry result. This does **not** imply 67 winners at causal exit: the no-cut causal opposite-local audit reports 67.16% winners (45/67 if rounded), while the *different exit policy* with a 1% cut reports 49.25% winners (33/67) and 22 stop exits. Comparing these two win rates as detector precision would be an error. Both reports have 67 observations, but stable trade-ID matching remains unverified.

The 1% cut report: 34/67 non-positive, 22/67 stop exits, therefore >=12/67 non-positive exits not due to the fixed cut, **conditional on every cut exit being negative after fees**. Exact exit reasons are unverified without a ledger. There is no evidence that any previously rejected MFE overlay fixes these 12.

## New risk budget calculation — equal-price-stop, not a replay
With a fixed 1.00% adverse-price cut and assumed 0.15% round-trip notional cost, the *no-gap modeled loss* is 1.15% of notional. Therefore to target 0.25% or 0.50% equity loss, max account notional exposure is respectively 0.25/1.15=**0.217391x** and 0.50/1.15=**0.434783x**, before funding or gaps. At 25x instrument leverage these correspond to **0.8696% and 1.7391% of equity posted as initial margin**. A separate 1% adverse execution gap raises assumed total price+fee loss to 2.15% notional, reducing exposure caps to **0.116279x** and **0.232558x**. These figures assume the gap is measured as additional price movement from the intended stop; they are NOT guaranteed maximum losses. Maintenance margin, mark-last divergence, order trigger, spread and funding remain UNKNOWN.

The published 3x baseline with a 1% cut has no-gap modeled stop loss 3.45% equity (3 x 1.15%), which is **6.9 times** the 0.5%-risk target. Thus comparing terminal compound at 3x to risk-capped alternatives without a shared replay is invalid.

## Data provenance blocker
`m1_stop_order_ambiguity_replay_20261116.py` correctly treats stop touches as fill-UNKNOWN and excludes stop-bar extremes from confirmed pre-stop MFE. `trade_manifest_gate_research.py` accepts source labels but cannot prove that a private fill, mark sequence or stop order actually exists. Neither script is a 67-row event replay. Do not report zero liquidations or mark-to-market drawdown from these checks.

## Required next experiment
1. Locate the original 67-row ledger and join by side, UTC extreme/confirmation/entry/exit timestamps; reconcile 71 accepted vs 67 finalized and 22 stops.
2. Verify rich M1/Public Trades/mark/L50 coverage by trade, preserving UNKNOWN where absent. Require proof of protective-stop acknowledgement or label fill MODELED.
3. Compare frozen 3x baseline with risk 0.25% and 0.5%, identical chronological trades and identical cost assumptions, separately LOW→LONG and HIGH→SHORT.
4. Report equity by calendar month, intra-position mark-to-market DD, fills, stops, liquidations (UNKNOWN if mark/maintenance absent), and MFE captured/given back.
5. Keep rejected flow/MFE exits and ATR trails rejected unless truly unseen chronological forward demonstrates improvement.

No training, parameter fitting, new branch, production modifications or real orders.
