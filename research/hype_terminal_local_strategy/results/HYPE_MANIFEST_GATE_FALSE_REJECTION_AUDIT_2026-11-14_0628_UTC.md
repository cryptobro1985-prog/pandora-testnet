# HYPE execution manifest: false-rejection audit — 2026-11-14 06:28 UTC

Research only. No production changes, no real orders, no detector retraining.

## Source reviewed
- `trade_manifest_gate_research.py` (current research branch).
- `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`.
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`.

## New concrete audit: false rejection of winner-run exits
The existing manifest gate requires all of `stop_trigger_ts_ms`, `stop_fill_ts_ms`, `stop_fill_price` and `stop_fill_source` to be present and non-null for **every** trade. It returns `UNVERIFIED_STOP_EXECUTION` if either stop timestamp is null. However the frozen 1%-cut strategy holds surviving trades to a *causally confirmed opposite H1 local*, so a valid opposite-local exit has **no stop trigger and no stop fill**. The current gate therefore cannot verify those valid non-stop exits, even with a complete opposite-local fill log.

Of the 67 frozen simulated trades, only 22 were fixed-cut exits. Up to 45 remaining exits require a non-stop execution pathway (the report does not provide row-level event types to prove all 45 were opposite-local fills). This is a structural verification blocker, not a new performance estimate.

The source gate also unconditionally converts `stop_fill_price` to float and uses it in `min(p,s,q,ep,sf)`; setting the unused stop-fill price to null would additionally fail numeric validation. Its `stop_gap_fraction` is meaningful only for an actual stop exit. Finally, the required-fields tuple contains 25 keys (not 26), so the prior report's count should not be relied upon without recounting.

## Concrete reconciliation (no invented fills)
A valid research manifest must have an explicit `exit_reason`:
- `STOP`: requires actual stop trigger timestamp, stop fill timestamp, stop fill price/source, and a matched event sequence. If stop trigger exists but no fill, status must be unresolved rather than priced at the trigger.
- `OPPOSITE_LOCAL`: requires opposite-local *signal-available* timestamp, subsequent exit order submission, actual exit fill timestamp/price/source. Stop trigger/fill fields must be null if no stop occurred, and should **not** fail the gate.
- `OTHER`: classify separately; never silently treat as STOP or opposite-local.
- Both types require proof of a working protective stop during the position lifetime; order acceptance/cancellation and gaps are distinct from a stop fill.

For STOP and OPPOSITE_LOCAL, use `entry_fill_ts_ms < exit_fill_ts_ms`; no OHLC look-ahead. An opposite-local timestamp is not its available/confirmed timestamp. On identical-millisecond events without a venue sequence ID, mark ordering unresolved. Public Trades prints alone do not prove a private execution fill.

## Risk sizing audit (scenario only)
With stop distance 1%, round-trip fees 0.15% notional and *additional adverse gap* 1%, the stress loss is 2.15% of notional. Target 0.25% / 0.50% of equity gives notional limits 0.116279x / 0.232558x equity respectively, before adding funding or other costs. The hard risk budget can be exceeded by larger gaps, so these are scenario limits, not guarantees.

## Next required executable replay
1. Export 67 row-level frozen trade identifiers with local candidate time, signal-available time, order/fill time and exit reason; verify their presence before joining to rich M1/Public Trades/CVD/L50/liquidation/OI/mark artifacts.
2. Split exit manifests by STOP vs OPPOSITE_LOCAL and count unresolved rows by missing source, not as zero or loss.
3. Replay chronological event order with actual available data, preserve unchanged baseline, report fills and liquidation unknown separately.
4. Only then compare low-risk sizing, staged entries and profit protection on identical fills/fees/funding and untouched forward data.

## Evidence limits
No 67-trade matched event-tape replay performed in this checkpoint. No newly validated net PnL, monthly equity, MTM drawdown, MFE capture, or zero-liquidation result. This audit identifies a deterministic branch-logic problem by direct source inspection; it does not claim observed historical fill outcomes.
