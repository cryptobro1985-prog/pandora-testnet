# HYPE D250 entry-fill causal gap audit — 2026-11-17 11:30 CET
Research only. No retraining, production changes or orders.

## Inputs actually inspected
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` in the frozen branch.
- `d250_trade_replay_manifest_gate.py` in the frozen branch.
No individual UTC trade tape or historical exchange fills were available in this iteration. This is a code-level causal audit and deterministic risk calculation, **not** a historical event replay.

## New concrete finding: entry timestamp fail-open
The existing gate checks `h1_confirmed_utc <= d250_signal_utc <= entry_utc`. Equality is accepted. It also checks `feature_asof_utc <= d250_signal_utc`. Thus it can mark as eligible an entry at precisely the signal timestamp, with features finalized at that same timestamp, without any proof of event ordering, dissemination latency, or first executable quote. A complete-coverage string does not resolve this. This applies symmetrically to LOW/LONG and HIGH/SHORT.

A causal fill proof must have **separate** `feature_available_utc`, `signal_emitted_utc`, `order_submitted_utc`, `exchange_ack_utc`, `first_fill_utc`, and ordered exchange event IDs; for a marketable order require feature_available <= signal_emitted < order_submitted <= exchange_ack <= first_fill, with same-timestamp ordering only if supported by reliable sequence IDs. Without this evidence classify **UNVERIFIED_FILL**, not zero-slippage executable.

The existing `D250_TOO_EARLY` check uses signal minus `local_extreme_utc` >= 250 minutes, not signal minus confirmation; this is the implemented rule, not proof that 250 minutes after extreme was the intended semantic definition. Freeze the existing rule until original definition is verified; do not silently redefine it.

## New quantitative sensitivity: entry-delay adverse selection (deterministic)
Assume frozen 1% adverse-price stop, baseline 0.15% round-trip notional costs, **additional** execution slippage 0.10% of notional per round trip, and initial risk budget 0.25% or 0.50% equity. Total modeled loss fraction per notional at stop = 0.0100+0.0015+0.0010 = 0.0125.
- 0.25% equity risk: max notional/equity = 0.0025/0.0125 = **0.2000x**.
- 0.50% equity risk: max notional/equity = 0.0050/0.0125 = **0.4000x**.
- At 25x instrument leverage, isolated initial margin/equity = **0.80%** and **1.60%**, respectively.
- If adverse stop gap adds another 0.50% of notional beyond this allowance, realized modeled equity loss = 0.20*(0.0125+0.005)=**0.35%** or 0.40*0.0175=**0.70%**. This is not a loss guarantee.
- If the trade's available structural stop is 0.6% instead of 1%, sizing must use the actual closer stop (plus costs and gap reserve) and verify stop is on the adverse side. Do not infer a structural price from the median 3.14%.

## Frozen baseline reconciliation
The source explicitly reports 67 sequential trades, 22 fixed-cut exits, 5x ending equity **$1,308.86** and closed DD **29.36%**; 3x ending equity **$531.16** and closed DD **18.56%**. Do not mix the 3x equity with the 5x DD or describe these as live / MTM results.

## Fail-closed event replay contract
For each trade: verified terminal-local confirmation timestamp, frozen D250 feature availability, directional signal, earliest executable order time, order book/trades at entry, partial fills, entry VWAP, mark-price path, stop trigger basis, actual stop fill with gaps and fees, funding, maintenance-margin/liquidation threshold, opposite-local confirmation, exit order/partial fills and VWAP, capital reservation across overlapping positions. Report separate LOW->LONG and HIGH->SHORT with identical samples/cost assumptions for baseline vs low-risk alternatives. No future opposite extreme may define exit. Report monthly net equity, closed and MTM DD, MFE captured/given back, and independently sealed forward outcomes **only after event-tape validation**.

## Decision
No new overlay promoted. Previously rejected profit-protection variants remain rejected. Until event-level matching, stop fill, and latency evidence are present, the honest status is **execution replay blocked** and no new empirical PnL, fills, liquidation counts or MFE retention claims are justified.
