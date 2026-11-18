# D250 event evidence: strict boolean fix — 2026-11-18 07:28 CET

Scope: existing research branch, frozen D250 unchanged, no detector retraining, no orders.

## Concrete change
Updated `d250_event_causality_gate_20261118.py` in place (commit `5db8e8b101dd5ad0d10f366636898e7366187230`).
The three evidence booleans now require exact Python `True` rather than Python truthiness:
- `scan_includes_both_endpoints`
- `sources[*].continuous` (M1, public trades, mark)
- `raw_tape_validated`

JSON strings `"false"`, `"true"`, numeric 1, null, and missing flags no longer qualify as true. Valid JSON `true` remains accepted. The gate still returns only `PRELIMINARY_CAUSAL_PASS`, not execution validation.

## Reproducibility
Read old module and previous bypass audit from this exact branch, applied minimal string substitutions, and committed through GitHub contents API. This iteration did not execute the Python module against real manifests or raw Bybit archives. Strict-identity behavior follows Python semantics; a real integration regression remains required.

## Evidence and limitations
This change repairs a proven evidence-contract defect but does not prove any particular HYPE trade was invalid or profitable. The original 67-trade per-trade UTC ledger and matched Bybit tick/L50/mark execution data remain unverified in this iteration. No new net equity, MTM DD, liquidation count, MFE capture, or forward performance is claimed.

## Next empirical work
Run the updated gate against the original manifest, independently scan actual raw M1 timestamps (not producer flags), recover matched per-trade UTC paths, and replay LOW→LONG and HIGH→SHORT with realistic gap/slippage, risk-based sizing 0.25–0.5% equity, total stop-risk ≤1%, funding and fees. Keep rejected MFE overlays rejected pending independent evidence.
