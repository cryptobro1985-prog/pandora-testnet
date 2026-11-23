# D250 strict execution-order audit — 2026-11-23 16:28 CET

Research only. No orders, no retraining, no baseline changes.

## Sources read directly from target branch
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- results/HYPE_D250_CAUSAL_CLOCK_ELIGIBILITY_2026-11-23_1535_CET.md
- d250_preentry_event_replay_gate_20261121.py
- d250_trade_replay_manifest_gate.py

## New concrete source-code audit finding
The preentry gate accepts `extreme <= confirm <= signal <= entry` and the trade manifest gate accepts `signal <= entry`. Neither gate records or verifies a quote exchange event ID, quote receive timestamp, nor strictly positive ordering between decision and executable quote. Therefore a manifest with `entry_utc == d250_signal_utc` can pass both temporal inequalities even if it assumes the closing price of the bar used to compute D250 features. This is a demonstrable validation gap in the inspected code, NOT proof that any of the 71 historical rows exploited it.

A second distinction: `h1_confirmed_utc <= d250_signal_utc` only validates timestamp labels; it does not prove the confirmation was delivered to the strategy before feature evaluation. UTC exchange-event time and local ingestion/availability time must be separated when the original event feed is available.

## Exact negative-control boundary cases (deterministic logical evaluation)
1. signal 04:10:00.000, entry 04:10:00.000: current gates allow equality; strict quote-after-decision must BLOCK absent sequenced event evidence.
2. signal 04:10:00.000, quote event 04:10:00.001, observed receive 04:10:00.005: earliest fill event can only be after receipt plus modeled decision/order latency, not 04:10:00.001.
3. signal 04:10:00.000, quote received 04:10:00.005, order submitted 04:10:00.010, next executable quote 04:10:00.020: admissible replay quote is 04:10:00.020 or later.
4. feature close 04:10:00.000, feature available 04:10:00.100, entry 04:10:00.050: BLOCK (feature not yet available).
5. same millisecond timestamps but explicit monotonically increasing feed sequence numbers: allow only if decision was committed before the later quote, order latency is satisfied, and the sequence ordering is independently attested.

## Proposed fail-closed replay invariant (do not retrofit to frozen results)
For each accepted local, persist `t_extreme_bar_close, t_pivot_available, t_feature_last_event, t_feature_available, t_decision, t_order_submit, t_quote_receive, t_fill` and independent event IDs. Require `t_decision >= max(t_pivot_available,t_feature_available)`; `t_order_submit >= t_decision`; `t_fill >= t_order_submit + latency_assumption`; and a quote observed no earlier than the order's simulated arrival at exchange. Same-time equality requires a verified total event order, not just matching UTC timestamps. Reject missing timestamps/sequence IDs, not fill with zero latency. A quote seen by the strategy before order submission is NOT automatically executable at that price.

Apply identical quote/latency convention to original baseline and 0.25%-0.5% risk alternatives. Side-specific fill: LONG buy ask / sell bid, SHORT sell bid / buy ask. Mark-price stream separately governs liquidation, not assumed trade fill. A stop is a contingent order with gap/slippage and must be sequenced against liquidation triggers.

## Scope/result
This iteration reviewed two actual existing validators and established a specific permissive equality boundary. No 71-row raw signal manifest, exchange event sequence, or matched quote tape was loaded. Newly certified historical fills: 0 (unknown rather than proven absent). No new net equity, MTM drawdown, MFE or liquidation result. Original frozen thresholds, 71/71 historical detector score, and rejected overlays remain unchanged.

## Next reproducible test
Construct a small fixture with five cases above; run the unchanged original validators to document which equal-time cases pass; then introduce a separate strict execution gate, without modifying baseline, and run both against the same immutable 71-event cohort once provenance-verified quote and receipt timestamps are available.
