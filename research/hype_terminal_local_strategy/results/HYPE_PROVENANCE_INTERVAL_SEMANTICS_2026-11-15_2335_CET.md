# HYPE execution evidence: event-vs-path interval semantics — 2026-11-15 23:35 CET

Research-only code audit + deterministic counterexample; not a Bybit tape replay, not a trade performance estimate. No detector retraining or production changes.

## Read directly from branch
- `research/hype_terminal_local_strategy/strict_execution_provenance_research.py`
- `research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
- Previous period-boundary equity checkpoint.

## New verified source-code finding
The strict gate applies one **full entry-to-exit coverage condition** to every evidence type:

```python
if start > row["entry_fill_ts_ms"] or end < row["exit_ts_ms"]:
    return {"status": "UNKNOWN_EVIDENCE_TIME_COVERAGE", "field": field}
```

This is valid for continuous **mark/L50/public-trades/event-sequence** paths (subject to gap and schema validation), but **invalid for point-event evidence** such as entry fill, exit fill, stop order acknowledgement and stop fill. A legitimate entry-fill event with coverage [entry_ts, entry_ts] necessarily fails whenever exit_ts > entry_ts; a legitimate exit-fill event [exit_ts, exit_ts] necessarily fails whenever entry_ts < exit_ts. Thus a properly event-scoped manifest cannot pass without artificially broadening event-file coverage metadata. Conversely a broad metadata interval is not proof the individual event occurred.

## Deterministic reproduction (pure Python)
```python
entry, ack, trigger, stopfill, exit_ = 1000, 1002, 2000, 2001, 2001
def current_gate(start, end): return start <= entry and end >= exit_
assert current_gate(entry, entry) is False     # legitimate entry-fill event rejected
assert current_gate(exit_, exit_) is False     # legitimate exit-fill event rejected
assert current_gate(ack, ack) is False         # legitimate stop-ACK event rejected
assert current_gate(0, 3000) is True           # broad interval accepted even without parsing event
```

## Required type-aware gate before 67-trade execution replay
- EVENT: verify immutable event ID, instrument, side, order ID, fill quantity/price, event timestamp, and linkage to trade ID; event must fall within an appropriate bounded tolerance of expected timestamp, not cover the entire holding interval.
- PATH: verify real source schema, symbol, event timestamps, monotonicity, per-minute coverage, maximum gap, L50 validity/crossed-book checks, and hash; path must cover entry through exit.
- STOP ORDER: require exchange ACK/order state **before exposure begins**, or explicitly label any entry-to-ACK interval as unprotected; current `entry_fill_ts <= ack < exit_ts` permits post-entry ACK.
- STOP FILL: require stop trigger, order linkage, actual simulated execution rule and adverse gap/slippage; distinguish synthetic fills from exchange-private fills.
- CAUSAL LOCAL: strict H1 K2 availability and D250 watermark before entry; opposite-local exit at availability, never at retrospective extreme.
- Preserve missing rich sources as missing; do not zero-fill.

## Concrete consequence for risk evaluation
The 67-trade 1% cut report assumes a 0.15% round-trip notional cost and a modeled stop price. Its 22 cut exits cannot be promoted to real protected fills by passing the current hash gate. In particular, an ACK after entry can leave exposure unprotected even when the gate returns its highest status. No observed liquidation-free claim follows.

## Frozen experiment contract
Original D250 thresholds unchanged: rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. LONG after confirmed LOW, SHORT after confirmed HIGH. The 1% adverse cut remains a baseline challenger, not a guaranteed fill. Preserve rejected tight trailing, raw-flow/MFE, and K0/K1 overlays.

Next execution run must first inventory real event-level artifacts and match trade IDs to source files. Replay baseline and 0.25%-0.5% stop-risk candidates on identical chronological trades with shared capital, same fees/funding/slippage, both closed and MTM DD, liquidation distance and MFE giveback. Do not publish missing metrics as zero.

## Status
Completed a new source-level execution-gate audit with a four-assertion deterministic counterexample. No real Bybit fill/L50/mark event join or independent forward PnL performed; all trade-level performance metrics remain unverified. No live orders, production modifications or new branches.
