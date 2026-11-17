# HYPE frozen D250: stop-distance / risk-budget feasibility audit — 2026-11-17 08:35 CET

Research only; no orders, no detector retraining, no claim of matched event replay.

## Verified source inputs
Read `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `d250_trade_replay_manifest_gate.py` directly from this branch.

- D250 frozen thresholds unchanged: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; side-normalized flow15 < 0.4504731635235635.
- 67 finalized next-opposite-local entries; 22 fixed-cut exits in separate asymmetric-risk simulation; structural diagnostic median stop distance 3.140% of entry price.
- 1% adverse cut is **closer** than the diagnostic structural median stop, and therefore is a price stop inside the structural invalidation zone, not a structural stop.
- D250 study reports worst observed pre-exit MAE -1.958%; a 1% cut will stop some trades that eventually had positive oracle next-local potential. Do not claim 67 oracle winners imply 67 executable winners.
- Original 5x account exposure = 25x instrument leverage × 20% account margin, not 0.5% equity stop-risk.

## Reproducible algebraic sizing comparison (not historical fills)
Let E=equity, d=adverse price stop distance, c=round-trip fee/funding/slippage reserve as fraction of notional, r=maximum intended loss fraction of equity, and N=notional. Then N/E <= r/(d+c). Use c=0.0015 solely to match the published round-trip cost assumption; no claim this is a full gap reserve.

| d | r | N/E maximum | Margin/E at 25x | Nominal loss/E at stop |
|---|---|---|---|---|
| 1.00% | 0.25% | 0.217391x | 0.869565% | 0.25% |
| 1.00% | 0.50% | 0.434783x | 1.739130% | 0.50% |
| 3.14% | 0.25% | 0.075988x | 0.303951% | 0.25% |
| 3.14% | 0.50% | 0.151976x | 0.607903% | 0.50% |

With 1% stop and 5x original account exposure, modeled stop+fee loss is 5 × (0.01+0.0015) = **5.75% equity**, 11.5–23 times the proposed 0.25–0.5% risk budget. Reducing nominal exposure alone preserves the same entry/exit trade signs before nonlinear fills and costs, but does not establish positive net return.

A 1% stop price is LONG entry×0.99 and SHORT entry×1.01. Actual stop fill is not guaranteed at trigger; adverse gap and slippage must be added to c and verified from trade/mark/book events. For 25x isolated leverage, margin and maintenance/mark-price liquidation buffers must be independently checked per position, not inferred from stop trigger.

## New audit finding: manifest gate is insufficient for a replay
The current manifest gate only verifies `m1_coverage/public_trades_coverage/mark_coverage == COMPLETE` strings. It does not validate hashes, source paths, UTC interval coverage, executable bid/ask, actual mark-price liquidation trajectory, per-trade fees/funding, or absence of overlapping capital. It accepts `d250_signal_utc == entry_utc`, which is not executable evidence. Its output is correctly named `MANIFEST_ONLY_NOT_EXECUTION_REPLAY`.

## Required next executable checkpoint
Recover trade_id, LONG/SHORT, original local and confirmed UTC, D250 as-of timestamps, entry/exit UTC and price, stop price and stop trigger reason, original capital state for all 67 trades. For each interval verify rich M1/Public Trades/mark and L50/OI/liquidations only where present; report missing data as missing, not zero. Replay unchanged baseline and low-risk alternatives on identical chronological event tapes, using executable bid/ask or documented conservative fallback, shared fee/funding/slippage, stop gap, liquidation and MTM equity. Freeze all thresholds before chronological forward evaluation. Until then: monthly net equity, MTM DD, fills, liquidation count, and MFE retention **NOT VERIFIED**.

No new exit overlay promoted; previously rejected overlays remain rejected.
