# HYPE D250 — adversarial execution evidence gate, 2026-11-20 04:26 CET

Research-only. Existing branch, frozen detector and 1% baseline unchanged. No orders, no training, no production modifications.

## Concrete new work
Read the actual frozen D250 report, 67-trade asymmetric-risk report, current `execution_event_integrity_gate_20261120.py`, recovered GitHub Actions M1 inventory, and `research/hype_12p_clean_core/MANIFEST.json`. Inspected repository tree (1,043 entries) for original 67-trade execution ledger. Added executable adversarial regression `research/hype_terminal_local_strategy/test_execution_gate_adversarial_20261120.py` with four expected-failure cases. The regression was **not executed** in this run: local container cannot resolve raw.githubusercontent.com. These are code-path findings, not passed test outcomes.

## Three material fail-open conditions in current gate
1. `opposite_extreme_ts_ms < entry_fill_ts_ms` is not rejected if `opposite_confirmed_ts_ms > entry_fill_ts_ms`. A future opposite local may already have occurred before entry, violating the D250 eligibility rule that the next opposite strict local must not have occurred before the checkpoint. A genuine opposite-local chronology must be reconstructed from event data; do not rely on this gate alone.
2. `Quote.source="synthetic"` is accepted as nonempty provenance. This can return `QUOTE_PROVENANCE_ONLY` for fabricated or model-generated quote series; such status must never be interpreted as real Bybit event evidence.
3. If a quote's mark crosses `liquidation_mark`, `observed_mark_liquidation_boundary_cross=True` is set but `status` remains `QUOTE_PROVENANCE_ONLY`. This is a danger flag, not a successful risk gate. A promotion gate must fail closed on such observations, while still distinguishing modeled boundary crossing from verified liquidation.

The regression covers LONG and SHORT for the opposite-extreme chronology, synthetic quote provenance, and mark-boundary breach. It deliberately does not alter the existing baseline or assert any historical fill.

## Data recovery finding
A previously recovered Actions artifact **13650399622** is documented in `HYPE_RECOVERED_ACTIONS_ARTIFACT_M1_AUDIT_2026-11-17_1330_CET.md`: 157,375 compact M1 bars across Jul12–Nov03, not the original 67-row UTC execution ledger, not ordered bid/ask/L50 fills. The clean rich-data manifest identifies only July 17, 18, 29 as full rich UTC days (4,320 M1 bars, 496 snapshots). Later rich L50/OI/liquidation coverage is missing. Attempts to query Actions artifact metadata through the currently available generic GitHub fetch endpoint returned unsupported-endpoint errors; that is **not** evidence of artifact expiry. Repository tree has 1,043 entries but no verified matched 67-row execution tape.

## Required next execution work
Recover immutable 67 trade IDs, side, extreme UTC, local-confirmed UTC, D250 eligibility UTC, order/fill UTC, stop/exit UTC; recover event-order bid/ask, L50, Mark Price and funding per interval. Enforce `opposite_extreme > entry` for the D250 hold-to-opposite candidate where required, provenance whitelist and independent event hashes, liquidation-danger fail-closed. Compare unchanged 3x/5x original baseline against 0.25%/0.5% risk-budget, mandatory stop and staged entry using identical trades, funding/fees/slippage, chronological no-capital-reuse equity; only then report monthly net, MTM/closed DD, fills, stops, liquidations and MFE. Rejected profit-lock overlays remain rejected without independent evidence.

## Evidence status
0 newly verified individual historical fills; 0 new historical event replays; no new defensible net PnL or liquidation-free claim. This checkpoint documents concrete code-path adversarial cases and new test code, **not** a completed replay or executed regression.
