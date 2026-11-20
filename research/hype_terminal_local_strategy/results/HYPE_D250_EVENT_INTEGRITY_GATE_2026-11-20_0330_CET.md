# HYPE D250 event-integrity checkpoint — 2026-11-20 03:30 CET

Research-only. No live orders, no detector refit, no production modifications.

## New concrete work
Read the original frozen 2026-11-12 D250 and asymmetric-risk reports and the current quote-event replay implementation. Added `research/hype_terminal_local_strategy/execution_event_integrity_gate_20261120.py`, a fail-closed per-trade gate that requires:
- strict chronology: original extreme < H1 local confirmation <= D250 data availability <= entry order <= entry fill;
- at least 250 minutes from the extreme to D250 availability, without substituting the extreme timestamp for actual K2 confirmation;
- opposite-local extreme < opposite-local confirmation, and exit confirmation after entry;
- monotonically increasing executable bid/ask + Mark Price observations, positive depth, non-crossed quotes, explicit provenance and maximum quote-gap control;
- a stop on the safe side of the supplied liquidation Mark boundary;
- conservative notional cap = equity * risk_fraction / (stop_fraction + round-trip fee_fraction + reserved adverse gap_fraction).

The module reports `QUOTE_PROVENANCE_ONLY` even when every check passes: neither L50 size nor top-of-book proves a market-order fill, and observed Mark boundary crossings do not establish actual liquidation events. The script contains deterministic synthetic regression assertions; it is not a historical replay and no new 67-trade result is claimed.

## Concrete risk calculation (not a backtest)
At $100 equity, 0.5% risk, 1% adverse stop, assumed 0.15% round-trip fee and hypothetical 2 percentage-point gap reserve: maximum notional = $0.50 / 0.0315 = $15.8730. At 0.25% risk: $7.9365. These caps do not guarantee losses cannot exceed risk in larger gaps.

## What was verified from preserved reports
- D250: 71/71 zero false-first on tested episodes, only 22.4% coverage, 67 finalized opposite-local paths, median 61.2% MFE giveback on causal opposite K2 exit.
- Asymmetric loss-cut: 67 simulated sequential trades, 22 stop exits, 3x $100->$531.16 and closed DD 18.56%; no verified L50 fills or MTM/liquidation safety.
- Existing `quote_event_stop_replay_research.py` uses executable bid/ask and returns hypothetical top-of-book fills; it explicitly does not verify liquidity or liquidation.

## Outstanding blocker and next action
No 67 individual UTC trade/event joins were obtained in this iteration. A credible paired replay needs each trade's local extreme and K2 availability timestamps, entry order/fill records, full interval bid/ask/L50 and Mark Price, funding, liquidation terms and source provenance. Then run identical chronological samples for original baseline and conservative sizing/staged entry/stop/profit-lock variants, with unmodified frozen thresholds and no overlapping capital. Until then monthly net equity, MTM DD, fills, liquidation count, and MFE protection remain **unverified**.

No rejected MFE overlays promoted. No branch created. No orders sent.
