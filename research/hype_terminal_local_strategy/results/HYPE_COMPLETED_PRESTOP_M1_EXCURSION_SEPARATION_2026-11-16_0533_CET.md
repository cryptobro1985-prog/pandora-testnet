# HYPE completed pre-stop M1 excursion separation — 2026-11-16 05:33 CET

Research-only incremental checkpoint. No D250 changes, detector retraining, production changes or real orders.

## Concrete replay defect and fix
The previous M1 replay already excluded the stop candle's favorable high/low from `mfe_upper_bound` when a stop was touched, but still returned `mae_upper_bound` including the stop candle's full adverse extreme. The candle's extreme may have occurred after the stop trigger, so this is not a verified pre-stop MAE. Both measures are now null when stop touched. Added `completed_pre_stop_m1_mfe_envelope` and `completed_pre_stop_m1_mae_envelope`, which only aggregate completed candles strictly before the first stop-touch candle. These are OHLC envelopes, not verified tradable MFE/MAE or execution prices.

## Deterministic regression
LONG entry 100, stop 99; first M1 bar open 100/high 102/low 99.5/close 100; second bar open 100/high 120/low 90/close 100. Correct output: STOP_TOUCHED_FILL_UNKNOWN; completed pre-stop MFE envelope 2%, MAE envelope 0.5%; stop-bar extreme +20%/-10% excluded; mae_upper_bound null. This prevents counting price movement after an unknown stop event as pre-stop exposure or available profit.

## Evidence boundary
Code and regression fixture committed. CI execution not verified. This is not a matched historical Bybit replay. No new net monthly equity, mark-to-market DD, fills, liquidation count, or independent forward evidence. Do not use 71/71 D250 detection statistics as execution proof. Preserve original baseline and rejected overlays.

## Next actual historical work
Find individual trade IDs/timestamps for the 67 episodes, hash-match M1 and Public Trades/L50/mark streams, distinguish LONG/SHORT and identify partial/unavailable intervals. Replay original unchanged baseline and conservative 0.25%/0.5% equity stop-risk with <=1% total stop risk on identical chronological episodes. Apply same fees/funding/slippage and capital constraints. Report monthly net equity, closed and MTM DD, stop gap uncertainty, liquidations, and causally protected MFE, withholding metrics when source evidence is absent.

Code commit: 02edd1596ab2f215105d8044e1a2623d5962e896
Regression commit: 34b2703e7d244c94e5bbfb943b07b55658d603f0
