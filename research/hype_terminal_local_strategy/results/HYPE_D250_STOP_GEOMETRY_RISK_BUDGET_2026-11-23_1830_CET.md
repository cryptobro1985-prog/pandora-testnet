# D250 post-local risk budget geometry — 2026-11-23 18:30 CET

Research only. No detector retraining, no order execution, no promotion.

## Source and actual calculation
Read the frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` in this branch and the existing `d250_trade_replay_manifest_gate.py`. The source reports median structural diagnostic stop distance **3.140%** from entry, median MAE **0.414%**, worst observed MAE **1.958%**, 67 completed opposite-local swings, and median MFE giveback **61.2%** on causal opposite-local exits. These are descriptive cohort summaries, not executable fills.

Calculated *before fees, slippage, gap, funding and minimum order constraints* with `notional/equity = risk_fraction / adverse_stop_fraction`:

| Equity risk | Stop distance | Max notional/equity | Margin/equity at 3x | Margin/equity at 5x |
|---|---:|---:|---:|---:|
| 0.25% | 3.14% | 7.962% | 2.654% | 1.592% |
| 0.25% | 1.00% | 25.000% | 8.333% | 5.000% |
| 0.50% | 3.14% | 15.924% | 5.308% | 3.185% |
| 0.50% | 1.00% | 50.000% | 16.667% | 10.000% |

**New decision-relevant finding:** a 1% adverse cut and a 3.14% structural stop are different hypotheses, not interchangeable stop settings. At 0.5% equity risk the theoretical allowed notional differs by 3.14x (50% versus 15.924% of equity). The 1% cut can close before structural invalidation; historical worst observed MAE of 1.958% demonstrates why its fill frequency and expectancy must be measured rather than presumed. Worst observed MAE is path-dependent and cannot establish that a 1% stop actually filled at 1%.

## Execution requirements
For each frozen signal, independently recover: local extreme UTC; H1 confirmation UTC; D250 feature as-of timestamps; decision and order send UTC; first executable post-send bid/ask; actual mark price path and liquidation threshold; stop trigger and order fill sequence; funding, taker fees, spread, slippage; subsequent causally available opposite local. Calculate LONG and SHORT separately. Missing event tape => BLOCKED, never zero-filled.

Compare unchanged baseline against 0.25%/0.5% risk with structural stop, 1% cut, staged entry, and profit protection on the identical chronological sample, while retaining rejected MFI+flow and fixed ATR trailing overlays as rejected. Cap aggregate stop risk at 1% and prevent capital reuse across overlapping positions. Report closed and mark-to-market drawdown separately and monthly net equity; unseen forward must remain untouched.

## Audit status
This checkpoint performs a **new deterministic risk-sizing sensitivity calculation on published real-cohort summary statistics**, NOT a matched event-tape replay. No new trade-level fills, realized returns, liquidation counts or forward performance are claimed. The referenced manifest validator explicitly states that COMPLETE coverage flags are assertions and do not verify exchange execution. Historical 71/71 classification is not 71 executable trades.

Frozen thresholds unchanged: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635.
