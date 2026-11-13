# HYPE safe post-Local entry: first risk-sizing experiment (2026-11-13)
Status: PAPER/RESEARCH ONLY; no orders and no unverified profit claim.

## Baseline source
`research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` already tested a **frozen** post-local entry + 1% adverse price cutoff and no tight trail, held until causally confirmed opposite local. In 67 simulated sequential trades and 0.15% notional roundtrip cost, 5x account exposure yielded $100->$1,308.86 over five noncontiguous historical windows but max CLOSED equity DD 29.36%; 3x exposure gave $100->$531.16 with 18.56% CLOSED DD. These are not evidence of safe prospective profitability, nor of no intra-trade liquidation.

## New concrete experiment: position risk instead of fixed leverage
Research-only `risk_budget_research.py` sizes HYPE entry according to:
`notional_fraction = min(risk_fraction/(stop_fraction + roundtrip_fees + extra_slippage + expected_funding), max_notional_to_equity, max_margin_fraction * exchange_leverage)`.
It reserves for roundtrip fees, execution slippage and forecast funding instead of risking only the headline stop distance. The script is not connected to orders.

For 1% underlying-price stop, 0.15% notional roundtrip fees, 0.10% reserved total slip, zero reserved funding (illustrative only), equity $100:
- 0.25% equity risk -> $20 maximum notional = 0.20x account exposure.
- 0.50% equity risk -> $40 maximum notional = 0.40x account exposure.
- 1.00% equity risk -> $80 maximum notional = 0.80x account exposure.
At 0.40% slip instead of 0.10%, with 0.5% equity risk, permissible notional falls to ~$32.26.
With 2x exchange leverage and 20% max margin allocation, notional is capped at 0.4x equity even if the calculated risk limit allows more.

These are **planned stop-loss estimates**, not hard maximum realized loss. Gaps, stale data, spread expansion, stop-market slippage, downtime, exchange liquidation rules and adverse funding can exceed the budget. More realistic mark-to-market/tick execution is required.

## Deterministic verification
`tests/test_hype_risk_budget_research.py` includes 6 regression checks; analogous standalone fixture run locally: 6 passed. These tests check sizing mathematics, not historic predictive skill or trade PnL.

## New distinction
The earlier 3x/5x historical "exposure frontier" is incompatible with *low* 0.25-0.5% stop-risk budget at a 1% price stop: 3x exposure would imply approximately 3.75% equity planned loss at a stop including 0.15% fee + 0.10% slip; 5x would imply ~6.25%, before worse-than-reserved fills. At 0.25% risk, nominal exposure must be ~0.20x, so previous high compound PnLs cannot be transferred to low-risk settings without a full trade-by-trade replay.

## Artifact access
The July full-micro FAILED workflow run id 42660911066 was queried through the GitHub run-artifact endpoint; it returned an empty artifacts list. This does not prove master/historical artifacts for other runs are absent. `research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json` notes 3 missing input IDs 111,112,113, and source file counts are NOT aligned time coverage.

## Next replay
Use the *same* 67 actual historical entry/exit event rows (or reconstruct deterministically from preserved data with causal timestamps); compare original frozen 1% stop and opposite-local exit under 0.2x, 0.4x, 0.8x notional versus historical 3x/5x. Mark every minute, apply real-side spread and slippage sensitivity, exchange funding and high/low stop-before-TP ambiguity. Report Sep/Oct and other separate periods: full daily equity curve, net PnL, trade count, funding, equity peak-to-trough and liquidation distance. Do not infer low-risk monthly return from scaling the high-exposure final equity alone.

## Research decision
Preserve current frozen entry. DO NOT raise leverage to compensate for reduced notional. Focus new experiments on credible causal exit after sustained control transfer and MFE preservation. No claim of 30%/month with low risk until OOS result proves it.
