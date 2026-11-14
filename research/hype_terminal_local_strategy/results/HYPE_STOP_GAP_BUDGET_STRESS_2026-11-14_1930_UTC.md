# HYPE stop-gap budget stress — 2026-11-14 19:30 UTC

Research only. No production changes, orders, new detector training, or promotion of previously rejected profit exits.

## Inputs checked
- Frozen D250 report `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: D250 causal entry filters unchanged; 71 accepted, 67 finalized opposite locals, 61.2% median MFE giveback.
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 1% adverse-price cut; 67 simulated sequential trades, 0.15% assumed round-trip cost, NOT a tick-by-tick execution replay.
- Existing `ohlc_execution_bounds_20261114.py`: conservative stop-first ambiguous-bar handling, but not observed fills.

## New reproducible stress
Added `research/hype_terminal_local_strategy/stop_gap_budget_stress_20261114.py`. It models hypothetical stop fills beyond the stop price, separately for LOW->LONG and HIGH->SHORT. Equity $100; budget $0.50/trade; fee 0.15% notional round-trip; nominal $23.255814 derived from 1% adverse cut + 1% additional stress slippage + fee. No funding included because hold times and rate history are not matched; results are not net trading PnL.

| Direction | Entry | Stop | Hypothetical fill | Total adverse price | Loss at $23.255814 nominal incl fee | Nominal to stay within $0.50 for this fill |
|---|---:|---:|---:|---:|---:|---:|
| LONG | 100 | 99 | 98.5 | 1.5% | $0.383721 | $30.303030 |
| SHORT | 100 | 101 | 102 | 2.0% | $0.500000 | $23.255814 |
| LONG | 100 | 99 | 95 | 5.0% | $1.197674 | $9.708738 |
| SHORT | 100 | 101 | 105 | 5.0% | $1.197674 | $9.708738 |

**Finding:** a $23.26 notional budgeted against a 2% adverse-price scenario loses approximately $1.20 (1.20% of equity) under a 5% adverse-price gap, more than double the intended $0.50 loss. This is a conditional scenario, not an observed HYPE price gap or fill. LONG/SHORT need their own empirical fill-gap distributions; a hard stop alone cannot guarantee a 0.5% equity loss bound. The table does not establish liquidation distance or actual executable liquidity.

## Execution replay requirements
1. Recover each of the 71 signal IDs, entry eligibility timestamp, stop placement/activation and all 67 finalized plus 4 censored outcomes; ensure strict H1 confirmation is available at entry time.
2. Match historical public trades and mark/index data to the stop trigger, book liquidity and spread at/after trigger, exchange order latency, partial fills and funding. Do not infer an executable stop fill from M1 OHLC.
3. For both sides, replay identical chronological sample with unchanged original 1% cut + opposite-local exit, then 0.25%/0.5% risk sizing, staged entry, mandatory stop and separately evaluated break-even/profit-lock proposals. Retain previously rejected overlays as rejected until independent OOS evidence.
4. Compute monthly closed and mark-to-market equity/DD, MFE capture/giveback, fill failures, stops, liquidation buffer and count, costs, and truly unseen forward outcomes; no overlapping reuse of capital.

## Evidence classification
New contribution is **deterministic synthetic stress calculation**, not a historical per-trade replay. The 67 trade records are still not matched to source market events in this checkpoint. Therefore there is no new validated net return, forward win rate, or zero-liquidation claim. No thresholds were refit.
