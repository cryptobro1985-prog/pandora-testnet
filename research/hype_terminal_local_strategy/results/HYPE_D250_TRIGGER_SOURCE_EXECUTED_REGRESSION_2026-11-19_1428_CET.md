# HYPE D250 stop trigger provenance: deterministic replay checkpoint
Date: 2026-11-19 14:28 CET. Research only; no orders.

## Source state
Read frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md and quote_event_stop_replay_research.py from this exact branch. D250 thresholds unchanged; 67-trade historical baseline unchanged.

## Executed new regression
Created stop_trigger_source_regression_20261119.py. Ran its equivalent deterministic Python code locally: **PASS 4 assertions** (two sides x two trigger sources). This is synthetic only.

LONG entry 100, stop 99: t1 bid 99.4, mark 98.7; t2 bid 98.8, mark 98.6. Mark-trigger stop first activates at t1, hypothetical bid exit 99.4; executable-bid-trigger first activates at t2, hypothetical bid exit 98.8. Gross price outcome differs by 0.6% of entry price. SHORT entry 100, stop 101: t1 ask 100.6, mark 101.4; t2 ask 101.3, mark 101.5. Mark-trigger hypothetical exit 100.6 versus executable-ask-trigger exit 101.3; difference 0.7% of entry price.

These are illustrative quote observations, NOT verified fills. They do not imply actual Bybit order execution at those prices. Last-price trigger is also supported as an explicit alternative, not inferred from bid/ask. The existing quote_event_stop_replay_research.py uses executable bid/ask to decide trigger; it does not accept stop trigger source and therefore cannot replay Bybit stop configuration faithfully.

## Required event-level join before historical promotion
For each of the original 67 sequential entries: immutable entry timestamp and filled VWAP, direction, actual trigger source (Last/Mark/Index, if known), trigger timestamp, last/mark/index series, executable bid/ask and L50 depth, order quantity, latency, partial fills, funding ledger, maintenance margin and liquidation tier. If source unknown: UNKNOWN_TRIGGER_SOURCE; do not select favorable source ex post. If depth/latency unavailable: UNKNOWN_FILL; do not count hypothetical top-of-book as verified. If mark stream missing: UNKNOWN_LIQUIDATION, not zero liquidations. Use same events, capital exclusivity, fees and funding for baseline and alternatives. Report MTM DD separately from closed DD and show independent forward partition.

## Interpretation
A stop threshold is NOT an executable fill price. A mark-trigger may activate before executable bid/ask crosses the nominal stop, and the reverse can occur. Trigger provenance changes both risk and time available to hold to causal opposite local. Do not optimize trigger choice on forward outcomes. Preserve 1% adverse cut and rejected overlays as baseline; no promotion without independent event replay.

## Current verification
4/4 synthetic assertions executed locally. 0/67 historical fills verified by this checkpoint. No new monthly net equity, MTM DD, realized MFE capture, or liquidation count. No detector training, new branch, production change, or real orders.
