# HYPE D250 — stop observability fail-closed verification (2026-11-20 21:30 CET)

Research-only. Existing frozen D250 unchanged. No detector training, production changes, or orders.

## Direct source review
Read existing branch files:
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (blob 54865475546c10cd555199c65a2a81ce0f14aab7)
- `quote_gate_followthrough_audit_20261120.py` (blob e70956a549b32383f8ca1e2cf768fbd32ca1c782)
- `results/HYPE_D250_STOP_OBSERVABILITY_BOUNDARY_2026-11-20_2030_CET.md` (blob e5ce1a093696374b7b14f59cb8cba9311b44fdd2).

## New executed verification
Implemented a separate, fail-closed research-only quote/Mark gate and executed it locally with Python 3 in normal and optimized (`-O`) mode: **10/10 deterministic checks passed in each mode**. Tests cover LONG/SHORT observed stop, already-breached stop, stale first quote, non-monotonic timestamps, crossed bid/ask, NaN Mark, unverified continuity, verified continuous Mark tape, and an unobserved inter-sample gap. Essential validation uses explicit `ValueError` rather than `assert` in the implementation; the test harness itself uses assertions and the optimized run's PASS output therefore is *not* independent proof of test coverage (the implementation's explicit validation is inspectable). The standalone research script was executed locally; this checkpoint does **not** claim it is deployed or merged into existing replay.

Key distinction: `NO_OBSERVED_TRIGGER_UNRESOLVED` vs `NO_TRIGGER_IN_VERIFIED_TAPE` requires affirmative external evidence of continuous exchange Mark-trigger observations, not simply closely spaced quote snapshots. A 1000ms intersample interval is an illustrative testing parameter, **not** a proven safe exchange-data threshold. Even `OBSERVED_STOP_TRIGGER` returns `verified_fill=false`; first post-trigger bid/ask is not an actual execution.

## Practical strategy consequence
Do not promote the previous 67 simulated trades or the 3x $100->$531.16 curve to execution-verified performance. A missing intratrade Mark segment can conceal a triggered stop. Keep both baseline and alternatives on exactly the same 67-entry chronology, label censored intervals, and exclude unidentified trades from point-estimate monthly net-equity / MTM / liquidation statistics rather than treating them as winners. No new historical matched fills were verified in this iteration.

Frozen D250 remains rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635 at D250. Entry is LOW->LONG / HIGH->SHORT only after causal confirmation, subject to no same-side extension or prior opposite local. Existing MFI+flow and ATR trailing overlays remain rejected.

## Next concrete data requirement
Recover the exact 67 UTC event identifiers and continuous Mark trigger evidence plus quote/L50, funding, fees, minimum order, margin tier, and liquidation parameters. Per event emit VERIFIED / CENSORED / MISSING; then reconstruct bid/ask depth-based fills, stop gap, risk-based notional 0.25%-0.5% equity and <=1% aggregate stop-risk, and paired baseline vs staged/BE/profit-lock vs opposite-local hold. No new net equity, MTM DD, stop count, liquidation count, or MFE-capture statistic is claimed.
