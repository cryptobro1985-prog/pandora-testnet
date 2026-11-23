# HYPE D250 directional stop-risk stress checkpoint — 2026-11-23 19:32 CET

Research-only deterministic stress calculation. No order placement, no detector retraining, no changes to frozen baseline. **NOT** matched event replay, no new empirical performance claim.

## Inputs and provenance
Read frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `HYPE_D250_STOP_GEOMETRY_RISK_BUDGET_2026-11-23_1830_CET.md`, and `d250_side_exact_stop_risk_v2.py` on the requested branch. The first reports 67 completed opposite-local swings, 3.14% median structural diagnostic stop distance and 61.2% median causal-exit MFE giveback. The second uses a 1% adverse cut and 0.15% round-trip cost **assumption**, not verified fills. The 1% cut was selected on development and must not be retuned on OOS.

New scenario (not verified exchange conditions): equity $100; entry reference $100; stop 1% or 3.14% adverse; fee 0.075% each side (0.15% total, for compatibility with historical assumption); entry slippage 0.03%; stop slippage 0.05%; additional adverse stop gap 0.20%; leverage 5x only for margin display; no concurrent positions. This is a sensitivity scenario, NOT a worst-case gap bound. Risk budgets 0.25% and 0.5% equity. Fees apply to actual entry and exit prices.

Direction-exact formulas: sign=+1 LONG, -1 SHORT; executed entry = 100*(1+sign*0.0003); stop reference = 100*(1-sign*d); adverse stop fill = stop reference*(1-sign*(0.0005+0.002)); loss per unit = sign*(executed entry-adverse fill)+0.00075*(executed entry+adverse fill); loss fraction of entry notional = loss per unit/executed entry; notional = equity*risk_fraction/loss_fraction. Do not infer liquidation distance from 5x alone.

## Calculated stress matrix
| Direction | Stop distance | Stop-loss incl assumed fees/slip/gap per notional | Notional at 0.25% equity risk | Notional at 0.5% equity risk | 5x margin at 0.5% risk |
|---|---:|---:|---:|---:|---:|
| LOW -> LONG | 1.00% | 1.4262% | $17.53 | $35.06 | $7.01 |
| LOW -> LONG | 3.14% | 3.5586% | $7.03 | $14.05 | $2.81 |
| HIGH -> SHORT | 1.00% | 1.4338% | $17.44 | $34.87 | $6.97 |
| HIGH -> SHORT | 3.14% | 3.5815% | $6.98 | $13.96 | $2.79 |

New decision-relevant result: the previous fee-free 0.5%-risk / 1%-cut estimate of 50% account notional becomes ~35% account notional in this explicit cost/gap scenario, and LONG/SHORT differ. At 3.14% stop it becomes ~14%, rather than 15.92%. These are **hypothetical exposure caps**; actual safe size can be smaller because of minimum quantity, margin fees, maintenance margin, liquidity and stress gaps. A gap worse than 0.20% can exceed the budget; a stop is not a guaranteed loss cap.

## Causal event replay still required
Restore immutable UTC identifiers for the 71 frozen signals; align H1 local confirmation and D250 feature availability, order send and first subsequent executable bid/ask, actual trade/L50 book tape, mark price and exchange liquidation tiers, funding and stop order fills. For each LONG and SHORT compare unchanged original baseline with risk-based sizing and fixed 1% cut, structural stop, staged entry and previously rejected overlays (rejected unless new independent forward evidence). Keep identical chronological trades and costs, enforce aggregate stop-risk <=1% equity and no overlapping capital reuse. Report monthly net equity, closed and mark-to-market DD, fills, stops, liquidations, realized MFE and giveback, independent unseen forward. **No verified replay performed in this checkpoint**.

Frozen D250 thresholds unchanged: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635.
