# HYPE post-local risk budget stress checkpoint — 2026-11-13 run 6

Research only; no orders, no production, no retraining, no thresholds modified.

## Verified sources read this run
- Frozen D250: 71/71 accepted true on preserved periods, 50/50 OOS; 22.4% coverage; 67 causal opposite-local exits median MFE giveback 61.2%. The rule is not a prospective 100% guarantee.
- Frozen 1% adverse-price stop, 0.15% assumed round-trip cost, 67 simulated sequential trades, 3x closed DD 18.56%, 5x closed DD 29.36%; mark-to-market DD and real stop fills unverified.
- Unified entry/MFE contract: no raw counter-volume exit; previously rejected trailing overlays remain rejected.
- Repo manifest contains references to master/rich artifacts, not a directly accessible matched 67-trade event tape.

## New reproducible numerical stress analysis
**This is a scenario calculation, NOT a historical Bybit replay.** Assumptions: 1% adverse price stop; 0.15% of notional all-in round-trip fees; an *additional* adverse execution gap of 0/0.5/1/2% of entry notional; zero funding, taxes, spread beyond these assumed charges. Loss/equity = account notional exposure × (0.01 + 0.0015 + gap). This is symmetric LONG/SHORT for equal absolute price movement approximation; actual short exact price/contract fee mechanics require event-level simulation. Exposure cap for target equity risk R = R / (0.0115 + gap).

| Extra adverse gap | Loss/notional | Exposure cap for 0.25% equity risk | Exposure cap for 0.5% equity risk | 3x equity loss | 5x equity loss |
|---:|---:|---:|---:|---:|---:|
| 0.0% | 1.15% | 0.2174x | 0.4348x | 3.45% | 5.75% |
| 0.5% | 1.65% | 0.1515x | 0.3030x | 4.95% | 8.25% |
| 1.0% | 2.15% | 0.1163x | 0.2326x | 6.45% | 10.75% |
| 2.0% | 3.15% | 0.0794x | 0.1587x | 9.45% | 15.75% |

At 1% extra gap, a 0.5% equity risk budget allows at most **0.2326x** account notional; 3x exposure would lose **6.45%** equity, 5x **10.75%**. A 1% stop is not a 1% equity risk bound. Even conservative scenario caps do **not** guarantee loss limits under larger gaps, exchange outages, liquidation or unmodeled funding.

## Actionable non-promoted sizing policy for independent testing
1. For each confirmed LOW->LONG or HIGH->SHORT, calculate actual stop distance from executable entry and verified liquidation price, mark price, margin tier, maintenance margin, and venue fees; reject if unknown. No fixed 25x leverage authorization.
2. Candidate budget 0.25%-0.5% equity/trade; combined worst-case stop-risk <=1% equity; use gap reserve calibrated from historical observed fills when recovered, not this hypothetical 1%.
3. Set account notional <= min(risk_budget/(stop_distance + all_in_cost + gap_reserve), available collateral constraint, verified liquidation-distance constraint). No overlap capital reuse.
4. Preserve original frozen baseline unchanged as comparator; do not promote any profit lock, staged entry or stop rule from this synthetic stress test.
5. Demand timestamp-matched 67 entries + Public Trades/M1 mark and actual orderbook depth to compute LONG/SHORT fills, stop gaps, monthly net and MTM DD, MFE captured, liquidation count, and untouched forward. Missing features stay missing.

## Provenance and claim boundary
Computed directly from frozen published stop and cost assumptions, with arithmetic shown above; no new historical performance, no actual stop-gap distribution, no new forward validation, and no claim of zero liquidations. GitHub directory inspection confirmed source code modules and reports exist, not availability of per-trade tick rows.
