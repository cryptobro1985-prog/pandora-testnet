# D250 stop-exit replay gate correction — 2026-11-17 03:30 CET

Research only; frozen detector unchanged; no orders.

## Source-level finding and correction
Read the frozen D250 report, original asymmetric-risk report and the previous manifest gate. The original gate unconditionally rejected `exit_utc < opposite_confirmed_utc`, even though the original 67-trade strategy includes **22 protective fixed-cut exits**. A valid STOP exit is specifically allowed before the next opposite H1 local is confirmed. This would have systematically excluded early stopped losses and introduced survivorship bias into any replay based on the gate.

Updated `d250_trade_replay_manifest_gate.py` to require `exit_reason` (STOP or OPPOSITE_CONFIRMED). The opposite-confirmation chronology check now applies only to OPPOSITE_CONFIRMED exits. All other existing frozen threshold, D250, causality, coverage and side checks remain unchanged. The `opposite_confirmed_utc` field is still mandatory for both classes: this is a **remaining limitation**, since stops without a finalized opposite local must ultimately be supported; the gate is not yet a full event replay.

## Deterministic regression scenarios (logic inspection; not CI execution)
- STOP at T+310m, opposite confirmed at T+500m: should not be rejected solely for early exit.
- OPPOSITE_CONFIRMED exit at T+310m, opposite confirmed T+500m: must be rejected.
- Unknown exit reason: must be rejected.
- STOP before entry: must be rejected by existing chronological sequence.
- A valid STOP with missing future opposite confirmation: currently blocked by required schema; fix before claiming complete 67-trade eligibility.

## What was actually achieved
Concrete source-level bug identified and corrected on the existing branch. No original 67-row UTC trade ledger or matched Public Trades/mark/L50 tape was read or replayed in this iteration. No verified fills, net monthly equity, MTM DD, liquidation count, MFE capture or unseen-forward performance. Do not treat these regression scenarios as real trades or claim tests ran.

## Next reproducible task
Recover 67 individual trade records and add an optional opposite confirmation for STOP rows, preserving exit reason and time; validate same-side invalidation from market tape. Replay STOP and OPPOSITE_CONFIRMED chronologically with identical cost assumptions and 0.25–0.5% equity stop-risk, ≤1% total stop-risk, and separate LOW/LONG vs HIGH/SHORT results. Previously rejected profit overlays remain rejected.
