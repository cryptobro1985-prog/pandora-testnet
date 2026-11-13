# HYPE safe post-local trade replay: stop-bar MFE chronology checkpoint — 2026-11-13

## Purpose and frozen baseline
Continue already-confirmed terminal H1 LOW->LONG, HIGH->SHORT research. No retraining, no threshold selection, no orders. The frozen D250 high-confidence entry (71 accepted true / 0 false-first in preserved historical audit, only ~22.4% coverage) and frozen 1% adverse price stop baseline (67 sequential simulated trades; 5x exposure closed-equity DD 29.36%) remain unchanged. Prior causal opposite-local exits gave median MFE giveback 61.2%; that statistic should not be recomputed with post-stop OHLC extremes.

## New experiment
Inspected `HYPE_PORTFOLIO_CAUSAL_ACCOUNTING_2026-11-13.md` and `HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`. The former identified a specific defect in the research minute-bar replay: if a bar contains both the stop and favorable extreme, the favorable extreme might occur *after* the stop. This creates phantom MFE and distorts both capture and giveback metrics.

Added `research/hype_terminal_local_strategy/stop_bar_mfe_bounds_research.py` and `tests/test_hype_stop_bar_mfe_bounds_research.py`. Six deterministic tests executed successfully locally (after replacing exact floating-point equality with tolerance-based assertions). This is a real executable regression, not a market replay.

The new function returns a lower and upper bound for MFE on a stop bar. Lower bound uses only prior completed-bar MFE and bar open (observed before intrabar extrema); upper bound includes the favorable high/low. If these differ and the stop is hit, MFE is AMBIGUOUS, not a single fabricated value.

Examples (illustrative, not HYPE price data):
- LONG entry 100, stop 99, stop bar O=100/H=105/L=98/C=101, prior best 102: stop is hit, true pre-stop MFE bounded between +2% and +5%.
- SHORT entry 100, stop 101, bar O=100/H=102/L=95/C=99, prior best 98: pre-stop MFE bounded between +2% and +5%.
- If previous completed bars already reached +4% and stop bar high is only +1%, MFE is unambiguously +4%.

## Empirical-data availability check
The manifest names `HYPE-HISTORY-20260712-20261103-MASTER`, `local116-HYPE`, `HYPE-RICH-STRONG-*` but these are references, not verified tick event streams. Queried July failed workflow run 42660911066 via Actions artifact API: returned [] artifacts. This is a single-run check and not evidence that all historical artifact families are gone.

## Decision and next experiment
Do not promote any MFE-based exit by counting an unknown post-stop high/low as reachable profit. First restore matched timestamped tick/public trade tape for 67 frozen entries and stop/exit times. Where only OHLC exists, publish conservative MFE lower/upper ranges, mark ambiguous bars and use stop-first trade PnL. Then compare original hold-to-opposite versus any new control-transfer exit on identical trade rows with fee/slippage/funding, separate LOW/HIGH, mark-to-market drawdown and no capital reuse. Existing rejected trailing/flow exits remain rejected.

No new claims of precision, net profit, liquidation-free trading or +30% monthly return are made.
