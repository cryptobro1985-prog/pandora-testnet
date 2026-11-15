# HYPE frozen 67-trade baseline: aggregate cost sensitivity and evidence boundary
Date: 2026-11-15 03:34 CET. Research only. No detector training, live orders, or production changes.

## Verified inputs (read directly from target branch)
- `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: frozen D250 rule, 71 accepted signals, 67 fully finalized next opposite locals, 4 censored; 50/50 OOS signal correctness is not an execution return.
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential modeled closes, 22 fixed 1% cut exits, 49.25% positive closes, mean winning equity return +14.16% and mean losing -4.37% at 5x exposure; fee model 0.15% of notional round trip.
- Previous event-tape audit confirms fill prices and start-to-exit raw market-event coverage are not yet demonstrated.

## New arithmetic audit: aggregate execution-cost sensitivity (NOT a trade replay)
49.25% of 67 is consistent with 33 winners and 34 non-winners (33/67 = 49.2537%).
Weighted arithmetic mean at 5x using rounded reported win/loss averages: 4.75672% of equity per closed trade. This is descriptive and is NOT a compounded return.
An additional **uniform** adverse round-trip execution cost δ of notional, on every trade, would subtract approximately 5×δ percentage points of initial trade equity from each modeled trade (fixed 5x exposure; ignores compounding, changing notional, partial fills, funding, and stop-induced changes).

| Extra cost per round trip (notional) | Extra equity drag at 5x | Approx arithmetic mean per trade |
|---:|---:|---:|
| 0.00% | 0.00 pp | 4.757% |
| 0.10% | 0.50 pp | 4.257% |
| 0.25% | 1.25 pp | 3.507% |
| 0.50% | 2.50 pp | 2.257% |
| 1.00% | 5.00 pp | -0.243% |

Arithmetic zero-mean sensitivity: 0.95134% additional notional cost per round trip. This is not a validated break-even slippage threshold: fills and stop incidence would change, and selection/compounding effects are excluded.

## Risk-based sizing contrast
At $100 equity, 0.5% total single-trade stop budget, 1% adverse-price stop, 0.15% round-trip fees and 1% adverse fill-gap reserve: max notional $23.26 (0.2326x equity). For 0.25% risk: $11.63. If multiple positions overlap, sum of worst-case stop losses must stay <=1% of current equity; gap risk is unbounded by a stop.
At 5x account exposure, nominal stop+fee loss is 5.75% equity, already >11 times the 0.5% exploratory risk budget before gap or funding.

## Explicit non-claims
No new market replay, fills, monthly net equity, MTM DD, liquidation count, or causal MFE retention established. The arithmetic table cannot be used to promote an overlay or predict a 0.23x equity curve. Original D250 and 1% adverse cut remain frozen. Rejected MFE exits remain rejected.

## Next data-dependent gate
Recover 71 signal rows with local/availability timestamps and original 67 trade ledger, then match raw Bybit Public Trades and order book at every entry/stop/exit; preserve four censored signals. Compute separate LOW/LONG and HIGH/SHORT execution costs, event-sequenced MFE, and same-sample risk-adjusted replay. Do not fill missing L50/OI/liquidation values with zero.