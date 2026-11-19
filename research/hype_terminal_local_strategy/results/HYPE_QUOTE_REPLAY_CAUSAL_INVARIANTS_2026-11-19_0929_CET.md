# Quote replay causal invariants — 2026-11-19 09:xx CET

Scope: research-only, existing frozen D250; no detector fitting, no orders. Source audited: `quote_event_stop_replay_research.py` (blob cc1a08310f2bf89580f789c66586b5f93363af6d).

## New concrete work
Added seven deterministic regression cases in `test_quote_event_replay_invariants.py` (commit 969645180e81eff8d7157f7c4155cb27a90b1352). They challenge LONG bid stop, SHORT ask stop, stop/opposite same-time ambiguity, pre-entry quotes, crossed book, no post-exit future extreme, and worsening stop-gap loss. They are **synthetic contract tests**, not a replay of the 67 historical trades.

## Numerical stop-gap case (independently hand-checkable)
LONG entry VWAP 100, 1% stop at 99, equity $100, risk 0.5%, round-trip cost 0.15%. Original function allocates notional 0.5/(0.01+0.0015) = $43.47826087; quantity 0.4347826087.
- executable bid 99: gross -$0.43478261; costs $0.06521739; net -$0.50000000 = -0.50% equity.
- executable bid 97: gross -$1.30434783; costs $0.06521739; net -$1.36956522 = -1.3696% equity.
Thus the nominal 0.5% risk budget is exceeded 2.739x on a 2%-point adverse stop gap. The existing engine does **not** reserve stop-gap or funding, and it assumes executable top-of-book quantity without L50 fill verification. This is a counterexample to treating the current sizing as bounded risk.

## Additional audit limitations
The `opposite_available` boolean lacks separate causal confirmation timestamp, event provenance, and order acknowledgement; a real exchange exit cannot be inferred from the flag alone. The engine returns `liquidation_verified=False`, not zero liquidations. It also does not compute monthly net equity or MTM DD. Frozen D250 high precision does not validate the trade execution model.

## Execution status
The GitHub connector successfully saved the test file. Direct checkout via local shell failed: DNS resolution of github.com unavailable. Therefore the new tests have NOT been executed against the checked-out repository and must not be reported as passing. Run `python -m unittest research.hype_terminal_local_strategy.test_quote_event_replay_invariants` in a repository-enabled runner and record its stdout/exit code.

## Next required evidence
Recover matched UTC entry/exit event ledger for all 67 sequential historical trades and real Bybit bid/ask/L50/mark/funding, preserve chronological OOS. Compare unchanged baseline and risk-budgeted stop-gap sizing on identical fills, with monthly net equity, closed and MTM DD, MFE, fills, stop gaps, and liquidation checks. Do not promote rejected MFE overlays without independent forward evidence.
