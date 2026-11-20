# HYPE D250: risk-cap semantics and chronology audit — 2026-11-20 06:32 CET

Research-only. No detector retraining, live orders, new branches, or production modifications.

## Evidence inspected in this iteration
Read from the named branch:
- `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `execution_event_integrity_gate_20261120.py`
- `execution_promotion_overlay_20261120.py`
- previous execution-promotion checkpoint.

Attempted GitHub Actions artifact listing using the connector's generic fetch URL; that endpoint was rejected as unsupported. No artifact bytes or 67-trade UTC tape were retrieved. This checkpoint is a code/quantitative audit, **not** an event replay.

## New concrete findings
1. The gate's notional formula `N = equity * risk_fraction / (stop_fraction + fee_fraction + gap_reserve_fraction)` is a **budgeted-loss estimate**, not a hard loss cap. It only constrains modeled loss while realized adverse execution slippage stays within the reserve; if a gap exceeds the reserve, realized equity loss exceeds the chosen risk. E.g. equity 100, risk .005, stop .01, round-trip cost .0015, reserve .02 gives N=15.87301587. At adverse move .05 from entry, loss = N*(.05+.0015)=0.81746032 USD = 0.81746% equity, exceeding the 0.5% budget. These are analytical stress numbers, not Bybit fills.
2. `validate()` has no account-level portfolio state or simultaneous open-position ledger. Thus it cannot enforce the requested maximum **aggregate stop-risk 1%**, prevent overlapping reuse of capital, or calculate chronological net equity / MTM DD.
3. `validate()` accepts a single user-supplied `liquidation_mark` and static quote marks. No exchange maintenance-tier calculation, funding/margin evolution, actual stop-order trigger type, latency, or L50 execution depth is reconciled. A quote-level mark boundary crossing is not a verified liquidation, and lack of crossing in sparse records is not proof of safety.
4. The overlay checks that the future opposite *extreme* did not occur before fill; the causal exit still requires an independently proven K2 confirmation-availability timestamp. The code accepts supplied timestamps, but does not establish their origin from raw H1 bars. Neither quote provenance strings nor local timestamps authenticate the tape.
5. The frozen D250 threshold rule and 67-trade baseline remain unchanged. In the original report, the 1% adverse-price cut was selected on development windows; rejected MFE exits cannot be promoted based on these checks.

## Consequence for promotion
Fail closed for historical execution claims until trade-by-trade entry/exit timestamp evidence, quote/mark/L50/funding, maintenance-margin tier and account-wide position state are recovered. Treat 0.25%-0.5% per-trade sizing as a provisional modeled cap, not guaranteed worst-case risk. Explicitly mark a stop gap beyond reserve as a **budget breach**, not as a successful risk-controlled stop.

## Required next reproducible replay
For each of 67 trades: original local-extreme and K2 availability timestamps, D250 features available by decision time, actual entry-side executable bid/ask, depth/latency, stop trigger/fill sequence, Mark Price, maintenance-tier/margin/funding and opposite K2 availability. Reject any missing critical field instead of substituting zero. Chronologically compare unchanged 3x/5x baselines, 0.25% and 0.5% stop-risk sizing, staged fills and separately frozen profit protection on exactly matched trades; track combined open risk <=1%, cash/margin constraints, monthly net equity, MTM/closed DD, realized fill costs, liquidation flags, MFE captured/given back and untouched forward periods.

## Status
0 new historical executions validated this iteration. No new net-return, MTM drawdown or liquidation claim. Research checkpoint only.
