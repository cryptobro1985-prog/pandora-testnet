# D250 combined research risk gate — 2026-11-22 01:28 UTC

Scope: existing frozen terminal H1 LOW->LONG / HIGH->SHORT entries only. No detector retraining, no production, no orders.

## Concrete change
Created `research/hype_terminal_local_strategy/d250_combined_risk_gate_20261122.py` at commit `4b27a266aa06418236a600a2a0b135d54ca088bd`.

Previous finding: `size()` can return `SIZED` even though the independently written liquidation clearance gate would block the candidate. The new composition calls `gate()` first and only then `size()`. It verifies identical side, entry, stop, liquidation price and assumed adverse gap across both inputs; mismatches block. A pass is deliberately labelled `RESEARCH_CANDIDATE_ONLY` with `not_executable=True`, never an order authorization.

The new module contains seven deterministic unit-test cases (LONG, SHORT, stale state, liquidation-input mismatch, other portfolio positions, unauthenticated state, and gap mismatch). These tests were added but have NOT been executed in CI or in this run.

## Limitations and next replay
The two underlying functions still rely on supplied hypothetical liquidation and stress gap inputs; composition does not validate exchange state, margin maintenance tiers, real-time mark, lot filters, funding or order fills. Do not claim zero liquidations or bounded actual stop loss. Next substantive task is locating the original 67-trade UTC manifest and event-level Bybit M1/Public Trades/L50/mark/funding files. Until they are matched, baseline vs low-risk equity, MTM DD, MFE, stop fills and independent forward cannot be reported.

Frozen D250 thresholds remain unchanged. Rejected MFE overlays remain rejected without new independent evidence.
