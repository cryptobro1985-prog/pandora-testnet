# HYPE D250 — fixed-notional gap reserve sensitivity — 2026-11-21 04:26 CET

Research-only arithmetic checkpoint. No detector training, no production change, no orders. Read directly from frozen `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` and `causal_exit_replay_research.py` in this branch.

## Frozen assumptions versus research stress
Frozen 67-trade historical simulation uses a 1% adverse-price cut and a *flat* 0.15% round-trip cost; this is not a verified bid/ask stop fill. Explore a **0.5% equity** stop-loss risk budget and an additional **2% of notional adverse-fill reserve**; this reserve is a hypothetical scenario, not observed Bybit slippage.

Fixed position notional / current equity = 0.005 / (0.01 + 0.0015 + 0.02) = **0.1587301587x**. Stop-risk of all concurrent positions must remain <=1% of equity, without reusing committed margin.

## New quantitative sensitivity: actual gap differs from reserved gap
Holding the same notional 0.1587301587x, full round-trip cost 0.15%, intended 1% stop, with an *actual additional adverse fill gap* shown below:

| Actual extra adverse gap / notional | Equity loss at same position | 0.5% budget |
|---:|---:|---|
| 0.0% | 0.183% | within |
| 0.5% | 0.262% | within |
| 1.0% | 0.341% | within |
| 2.0% | 0.500% | within |
| 4.0% | 0.817% | BREACH |

Formula: equity_loss = 0.1587301587 * (0.01 + 0.0015 + actual_gap). At 2% extra gap, equity loss = 0.5%. At 4%, it is 0.81746%: **63.49% over the 0.5% budget**. This is a deterministic gap sensitivity, not a historical loss distribution. Gap reserve is not a hard bound.

## Additional source-code inspection
`causal_exit_replay_research.py` uses default `exposure=.2`, `cost_pct=.0025`, OHLC-derived stop execution `min(stop,close)` for LONG / `max(stop,close)` for SHORT, and returns a `net_equity_pct` even if `exit_reason=OPEN`. Its output therefore cannot establish risk budget compliance or realized equity for 67 Bybit fills. These issues remain open; do not patch the original baseline.

## Explicit next replay gate
Use the original 67-trade UTC manifest, identify first quote *after* causal D250 signal; require marketable ask to enter LONG and bid to enter SHORT; stop trigger by independently recorded Mark Price, fill from later executable opposite-side L50 quotes (or mark UNRESOLVED). Calculate realized slippage relative to stop separately for LOW->LONG and HIGH->SHORT, with actual fees/funding and no OHLC-derived fill assumptions. Apply risk-based sizing using only ex-ante stop and conservative cost budget, reject if quote/tape is missing. Calculate MTM and closed DD on a single shared sequential capital ledger. No numerical strategy performance promotion without this data.

Frozen thresholds unchanged: rev_atr >2.084004943, trade_ratio5 >0.2727842248, side-normalized flow15 <0.45047316. Previously rejected profit overlays remain rejected. No independent forward result is claimed.
