# Frozen D250 cohort gate — semantic audit (2026-11-22 21:32 UTC)
Research-only. No orders, no production changes, no retraining.

## Inputs inspected
- d250_full_cohort_gate.py blob 6d47f9c00ee5f0a3a5f64eb182194bb16d90f3da
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md blob 54865475546c10cd555199c65a2a81ce0f14aab7
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md blob be76b9a61c86ec59c94b885eea4b15ee97cc1c05

## New static, reproducible audit of execution eligibility
The existing manifest gate is **not an execution verifier**. In particular:
1. It requires a 64-character source_sha256 but does not recompute that hash from any underlying tape. A syntactically valid invented hash passes.
2. It checks quote_coverage and mark_coverage equal COMPLETE but does not bind quote timestamps to entry/stop/fill events or verify bid <= ask, market depth, spread, mark/last basis, or exchange maintenance-margin tiers. Synthetic self-tests use placeholder prices and hashes.
3. It checks an opposite-ledger first timestamp, but that is not necessarily the timestamp at which the opposite H1 K2 local became *available*. Opposite exit eligibility must use K2 confirmation availability, not the future extreme timestamp. Any replay lacking distinct extreme_utc, k2_confirmed_utc, available_utc must be BLOCKED.
4. The D250 signal rule has no explicit check that the opposite local was absent **before D250** except indirect ledger fields. Complete source coverage must span candidate extreme through signal, not merely entry through cutoff. The existing opposite_ledger_start_utc <= entry_utc test permits a ledger beginning at D250, missing earlier invalidation.
5. The cohort_size_71 boolean checks count only, not identity against the frozen accepted-signal IDs. 71 synthetic unique IDs could satisfy this size condition.
6. The gate has no real fill/stop replay and no portfolio cash reservation, funding, stop-gap slippage, mark-price liquidation, MFE or MTM drawdown. Thus MANIFEST_ELIGIBLE_NOT_VERIFIED is explicitly not a trading approval.

## Concrete counterexample (logical replay, no invented market data)
Let local extreme be T0, signal T0+250m, entry T0+251m, observation cutoff T0+600m, opposite_ledger_start=T0+250m, opposite_ledger_end=T0+600m, opposite_ledger_first=NONE, and all declared coverage flags COMPLETE. This satisfies the gate's window checks, even if a real opposite H1 local occurred at T0+200m. The event is outside the declared ledger and is not detected. This is a causal eligibility hole, **not evidence that any actual D250 trade was affected**.

## Required next replay gate
- Bind each of 71 signal IDs to frozen cohort export and sha256 of actual raw source; 67 closed + 4 censored must reconcile without fabricated exits.
- Verify opposite and same-side ledgers from original extreme through entry and observation cutoff; use K2 *available* timestamps for both local confirmation and exit.
- For each LONG use executable ask entry and bid exit; reverse for SHORT. Match M1 public trades/CVD/L50/liquidations/OI by UTC and mark missing inputs UNKNOWN, never zero.
- Event-order replay stop before hypothetical opposite exit when chronological tape supports it; where OHLC alone cannot establish intra-bar ordering, label ambiguous, not favorable.
- Compare unchanged 67-trade baseline with risk-based 0.25%/0.5% equity sizing, aggregate 1% stop risk, gap/slippage stress, staged entries and previously rejected overlays as REJECTED unless independent forward evidence emerges.
- Compute monthly net closed and MTM equity, fees/funding, fills/stops, liquidations, MFE capture/giveback and independent forward results. No output metrics should be fabricated before real matched tape is found.

## Status
Completed a new static semantic audit and counterexample; did NOT execute 71-trade exchange-tape replay, validate actual source hashes, or measure net returns. Frozen D250 unchanged. Next cycle should prioritize obtaining original frozen cohort IDs and per-event UTC tape, then implement the above strict gating.
