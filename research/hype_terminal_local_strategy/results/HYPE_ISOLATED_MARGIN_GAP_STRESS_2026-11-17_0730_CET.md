# HYPE D250 — stop execution versus isolated margin stress (2026-11-17 07:30 CET)

Research only. No detector training, no production, no orders.

## Source verification
Read the existing branch files `d250_trade_replay_manifest_gate.py`, `test_d250_trade_replay_manifest_gate.py`, and `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` directly via GitHub connector. The original baseline uses a 1.00% adverse-price cut (or closer structural stop), 0.15% round-trip notional costs, 67 simulated sequential trades, 22 fixed-cut exits. The gate is only a manifest check; it does not inspect a matched trade/mark/book tape.

## New execution-risk stress calculation (deterministic, not historical replay)
For a position with 25x **isolated instrument leverage**, entry margin is nominal/25 = 4% of notional, before maintenance margin, fees and liquidation buffer. A price gap of 1%, 3%, 4%, or 5% against the position loses respectively 25%, 75%, 100%, or 125% of *initial isolated margin* before fees. Therefore a stop intended at 1% cannot be assumed executable during a 4%-5% gap; the liquidation threshold depends on exchange risk tier, maintenance margin, funding, mark price and margin mode. This is not a liquidation prediction.

Risk sizing, assuming total entry+exit costs 0.15% notional and **extra** gap beyond intended 1% stop:
- 0% extra gap: per-notional modeled loss 1.15%; notional/equity at 0.25% stop-risk = 0.217391x, at 0.5% = 0.434783x.
- 1% extra gap: loss 2.15%; the same positions lose 0.467391% and 0.934783% of equity respectively.
- 3% extra gap: loss 4.15%; the same positions lose 0.902174% and 1.804348% of equity respectively.
- 5% extra gap: loss 6.15%; the same positions lose 1.336957% and 2.673913% of equity respectively.

Formulas: N/E = risk_budget / (0.01 + 0.0015); gap_loss/E = (N/E) * (0.01 + 0.0015 + extra_gap). Fees/funding may be worse; stop-market fill and liquidations are not simulated. The conservative *stop-risk* budget is not a guaranteed maximum loss.

## Concrete replay gate finding
The current gate accepts `m1_coverage=COMPLETE`, `public_trades_coverage=COMPLETE`, `mark_coverage=COMPLETE` as unverified user-provided strings. It also accepts `d250_signal_utc == entry_utc` and `entry_utc == exit_utc` because the main chronology uses non-strict inequalities. Therefore `ELIGIBLE_FOR_EVENT_REPLAY` cannot be interpreted as proof of executable fills or strict post-signal sequencing. No aggregate return should be reported from this gate.

## Mandatory next evidence
Locate the 67-trade UTC-level ledger and exact underlying event files, hash source artifacts, verify event-level coverage per trade, use mark for liquidation/stop trigger, order-book/trade tape for attainable fills, resolve ambiguous within-minute high/low ordering pessimistically, and compare original baseline to 0.25%/0.5% risk sizing on identical chronology and costs. LONG/SHORT separately; no capital overlap. Report monthly net equity, MTM and closed DD, gap/slippage, MFE capture, fills, stops, liquidations and truly unseen forward. Missing evidence => NOT VERIFIED, never zero liquidations.

No historical matched replay was performed in this iteration; these are deterministic stress calculations and a source-code gate audit. Frozen D250 and previously rejected MFE overlays remain unchanged.
