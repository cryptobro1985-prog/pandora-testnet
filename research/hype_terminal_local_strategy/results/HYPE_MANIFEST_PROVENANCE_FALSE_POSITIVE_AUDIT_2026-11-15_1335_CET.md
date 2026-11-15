# HYPE execution manifest gate: provenance and liquidation verification audit — 2026-11-15 13:35 CET

Research only; no model retraining, no production or live orders. Existing frozen D250 and 1% adverse cut unchanged.

## Direct source inspection
Read `research/hype_terminal_local_strategy/trade_manifest_gate_research.py` and `stop_bar_mfe_bounds_research.py` from this branch, plus frozen entry and asymmetric-risk reports.

## Newly identified evidence limitation (code-level)
The current manifest gate returns `EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED` when source fields are merely **nonempty strings** and `coverage_complete is True`. It does not open those source files, verify hashes, establish their time coverage, check that private fill IDs exist, verify stop order acknowledgement, or reconstruct mark-price margin/liquidation events. The self-test uses strings such as `"private-fill"`, `"mark"`, `"l50"`, `"tape"`, `"sequence"`, `"order-log"` and obtains the success-like status by design. This is a structural *manifest completeness* test, not independent evidence of executed trades. Do not count any rows passing it as verified fills, no-liquidation trades or fully replayed events.

The gate also does not prove that the opposite local referenced by `opposite_local_ts_ms` is the opposite *type* or is the first causally available opposite terminal local. It checks ordering only. In addition, the stop path does not validate that the stop order existed before the trigger, only that a nonempty source string was provided.

## Reproducible static proof
1. In `trade_manifest_gate_research.py`, `sources` contains source-field names.
2. Condition: `row["coverage_complete"] is not True or any(not row[k] for k in sources)`.
3. Therefore any nonempty placeholder string passes the source check.
4. `self_test()` sets exactly such strings and asserts status `EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED`.
5. There is no external source dereference or mark-path liquidation computation in `gate()`.

## New mandatory evidence gates for matched replay
For every frozen signal: match signal ID to immutable exchange-event timestamp, side, entry eligibility and actual order/fill record (or explicitly tag hypothetical simulated fill). Validate source existence, SHA-256, covered start/end times and missing intervals. Require stop order acceptance timestamp preceding trigger; use actual private execution IDs for live fills and bid/ask+depth-based **simulated** execution for historical paper replay. Require mark-price path, margin mode, maintenance schedule and fee/funding path before reporting liquidation count; otherwise mark liquidation UNKNOWN. Require opposite-local ID/type, its causal availability timestamp and first eligible exit action. Treat missing or ambiguous events as UNKNOWN, not zero.

Compare unchanged original baseline to conservative 0.25%/0.5% risk sizing and staged/profit-lock challengers only on identical resolved trade IDs, dates and cost assumptions. Exclude overlapping reuse of capital. Do not resurrect previously rejected overlays without independent forward evidence.

## Status
This iteration is a direct source-code evidence audit, **not** a new 67-trade event replay. No new PnL, mark-to-market DD, stop fill, MFE capture or liquidation count can be asserted. The existing 71/71 signal-scoring claim is distinct from verified fills. Next priority: obtain the 67-trade ledger and underlying market tapes, then enforce the provenance gate before computing returns.
