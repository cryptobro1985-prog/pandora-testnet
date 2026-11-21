# D250 fixed-stop execution gap stress audit — 2026-11-22
Research only; no detector changes, no orders, no production modifications.

## Provenance
Read frozen report `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` and existing `d250_liquidation_clearance_research_gate_20261121.py` directly from the target branch. Frozen baseline reports 67 sequential trades, 22 fixed-cut exits, 3x $100->$531.16 and 18.56% closed DD; 5x $100->$1308.86 and 29.36% closed DD. These are not tick-execution or mark-to-market validated.

## New deterministic stress calculation
For either LOW->LONG or HIGH->SHORT, assume entry 100, 1.00% adverse trigger, round-trip notional fees 0.15%, and extra adverse execution gap g measured as fraction of entry. Approximate equity loss at exposure E = E*(0.01+0.0015+g). Gap is an additional execution loss beyond the 1% trigger, not a guaranteed upper bound. Funding, partial fills, basis and bankruptcy risk excluded. No historical replay is implied.

| Additional adverse gap | 3x exposure equity loss | 5x exposure equity loss | Notional / equity at 0.25% risk | Notional / equity at 0.50% risk |
|---|---:|---:|---:|---:|
| 0% | 3.45% | 5.75% | 0.21739x | 0.43478x |
| 0.5% | 4.95% | 8.25% | 0.15152x | 0.30303x |
| 1.0% | 6.45% | 10.75% | 0.11628x | 0.23256x |
| 2.0% | 9.45% | 15.75% | 0.07937x | 0.15873x |

The reported worst modeled 5x trade of -5.75% equals exactly 5*(1%+0.15%), which suggests it does not incorporate extra gap beyond trigger. This arithmetic is not proof of the underlying simulator's fill implementation. A 2% adverse gap would make the same position lose 15.75% equity before funding and other execution frictions. Thus 3x/5x baseline account exposures cannot be presented as consistent with the exploratory 0.25%-0.5% stop-risk budget.

## Execution geometry and failure modes
LONG: a stop trigger at 99 on entry 100 may fill below 99; SHORT: a trigger at 101 may fill above 101. Stop-market is not a guaranteed fill price. M1 OHLC cannot establish within-bar stop/target ordering. An isolated liquidation-clearance check using a single authenticated mark/liquidation snapshot cannot certify clearance after a gap, liquidation-price drift, portfolio margin changes, or stale mark. If precise public trades/orderbook are absent, record fills as unverified and stress as scenarios, not observations.

## Research gate for next matched replay
1. Recover original UTC trade manifest for all 67 baseline trades, with frozen signal time, entry time, side, H1 pivot confirmation, prices and cost assumptions; do not fabricate absent records.
2. Match actual Bybit M1/public trades/L50/mark/OI/funding timestamps, document gaps and coverage per trade.
3. Replay unchanged 67-trade baseline and alternative risk-based exposures on identical chronological fills, with capital reservation and no reuse while open.
4. Publish LOW and HIGH separately: signal->entry adverse excursion, entry-to-stop and stop-to-liquidation distance, realized slippage and fee/funding, MTM and closed DD, MFE capture/giveback, monthly equity and unseen forward.
5. Do not promote break-even, profit lock, control-transfer or staged-entry overlays until independent forward evidence exceeds the unchanged baseline under identical fills.

## Result classification
NEW: independently reproducible algebraic gap-stress table and explicit mismatch between fixed 3x/5x exposure and small risk budget.
NOT VERIFIED: historical stop fills, liquidity, liquidation count, equity returns, independent forward performance, or MFE protection.
