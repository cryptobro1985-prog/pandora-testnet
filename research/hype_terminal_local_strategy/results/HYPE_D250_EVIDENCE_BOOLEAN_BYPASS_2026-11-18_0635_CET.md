# D250 event-evidence boolean bypass — 2026-11-18 06:35 CET

Research only; frozen D250 unchanged. No detector retraining, production edits, or orders.

## Direct source inspection
Read the existing branch's `d250_event_causality_gate_20261118.py`, `d250_m1_continuity_audit_v2_20261118.py`, frozen D250 report, asymmetric risk report, and unified causal entry/MFE contract.

## New reproducible defect
The evidence gate uses Python truthiness instead of strict boolean validation:
- `not e.get("scan_includes_both_endpoints")`
- `not item.get("continuous")`
- `not e.get("raw_tape_validated")`

JSON string `"false"` is truthy in Python, so an evidence producer that serializes booleans as strings can bypass these three mandatory gates. A purported `PRELIMINARY_CAUSAL_PASS` is not independently proven even when flags are literally `"false"`. This is not evidence that any real D250 trade was wrongly passed; it is a reproducible contract defect.

## Executed regression
Ran Python 3 locally with the three exact keys assigned string `"false"`. All 3/3 current truthiness checks evaluated to true, whereas `value is True` correctly evaluated to false. The test is synthetic and not a historical trade replay.

## Required fail-closed correction
For JSON flags require `value is True`, not `bool(value)` or string coercion. For CSV booleans parse explicitly from a restricted grammar or reject. Independently verify continuity against raw files; never trust an asserted `continuous` field. Re-run the gate on every original signal after this correction, retaining blocked reasons.

## Execution status
No historical 67-trade UTC ledger or matched tick/L50/mark execution tape was recovered in this iteration; no fill simulation or new net PnL, MTM DD, liquidation count, or MFE retention is asserted. This finding concerns the evidence gate, not the D250 thresholds. Rejected exit overlays remain rejected.

## Next empirical priority
Recover the original 71 first-signal UTC rows and 67 completed trades; independently match archive hashes and event times, validate the full M1 windows with the v2 scanner, and replay LOW→LONG versus HIGH→SHORT using identical fee/funding/slippage assumptions, mandatory stop, 0.25–0.5% equity risk, and max 1% aggregate stop-risk. Missing rich features remain UNKNOWN.
