# HYPE frozen D250: pre-entry local chronology gate — 2026-11-21 16:35 CET

Research only. No detector training, production edits, or orders.

## New concrete work
Read the frozen 2026-11-12 D250 walk-forward report, the asymmetric risk report, the 2026-11-21 15:28 CET tracked-data inventory, and both existing eligibility/manifest gates directly from the requested GitHub branch. Created `research/hype_terminal_local_strategy/d250_preentry_event_replay_gate_20261121.py` as a separate executable, fail-closed pre-entry event chronology check. Existing frozen thresholds and baseline code remain unchanged.

The existing `d250_trade_replay_manifest_gate.py` verifies an opposite-event ledger starting at entry, not the period from original extreme to entry. Thus it cannot establish whether the original local remained valid through the 250-minute wait. The new gate requires independent event records, original anchor matching, chronological timestamps, pre-entry coverage, and event provenance; it blocks same-side extensions and premature opposite confirmations before signal **and** before actual entry. It reports reasons per trade and does not call a pass an executed trade.

## Critical limitation and non-leakage
A list of confirmed H1 pivots is not sufficient to prove absence of an interim lower LOW or higher HIGH: an extension can occur before the later pivot is confirmed. Independent raw M1 price-extreme verification is still mandatory. Likewise, `preentry_event_coverage=COMPLETE` and `event_source_sha256` are assertions, not cryptographic verification or proof of complete exchange coverage. Never infer missing event = no event from incomplete tape.

## How to run (once real inputs are recovered)
```bash
python research/hype_terminal_local_strategy/d250_preentry_event_replay_gate_20261121.py \
  original_67_trade_manifest.csv independent_local_events.json --out preentry_audit.json
```
Manifest needs `trade_id,side,local_kind,local_extreme_utc,h1_confirmed_utc,d250_signal_utc,entry_utc,preentry_event_coverage,preentry_event_start_utc,preentry_event_end_utc,event_source_sha256`. Event JSON needs `kind,extreme_utc,confirmed_utc,event_id`. All times offset-aware UTC. This gate complements, never replaces, the frozen threshold gate and event-level execution replay.

## Results and blocker
**New source artifact committed, but no real trade-level replay was executed**: the original 67 UTC entry records and matched Bybit Public Trades/mark/L50/OI/liquidation tapes were not available in the inspected tracked research directory. No fabricated features or prices were used. No new monthly net equity, mark-to-market DD, stop-fill statistics, liquidation count, or MFE retention can be reported. No independent unseen forward sample was evaluated.

Frozen observations remain historical and not live verified: 71/71 accepted D250 first signals on tested periods, 67 completed opposite-local episodes, median causal MFE giveback 61.2%; 67-trade asymmetric 3x paper account $100->$531.16 with 18.56% closed DD, without execution verification.

## Next replay priority
Recover the immutable original 67-trade manifest and source tape locations. Verify actual same-side raw M1 extensions between extreme and entry; join per-trade UTC public trades, mark/quotes, fees/funding and liquidation estimates. Then compare unchanged original 1% adverse cut to 0.25%/0.5% stop-risk and max 1% portfolio stop-risk with identical chronology, no double-used capital, realistic gaps/slippage, LONG/SHORT separation, MTM and closed DD. Keep rejected trailing overlays rejected until independent forward evidence.
