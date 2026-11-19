# Frozen D250 — execution-risk sizing and stop-gap sensitivity (2026-11-19 01:33 CET)

Research only. No orders, training, threshold fitting, or production changes.

## Verified repository inputs
Read directly from branch research/hype-h1-local-v5-oi-microstructure-20261104:
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: D250 >250 min after extreme; 71 accepted (50 OOS), 67 finalized opposite locals, median causal opposite-exit MFE giveback 61.2%; structural-stop median entry distance 3.14%.
- results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 1.0% adverse entry-price cut selected on development data; 0.15% round-trip cost assumption; 67 sequential simulated trades; no execution-level mark/fill validation. The 1% cut is not a guaranteed executed loss.
- d250_trade_replay_manifest_gate.py: audit returns eligibility based on asserted coverage and chronology, not an exchange-matched fill replay; no independent stop gap or liquidation check.

## New deterministic stress calculation, not historical replay
Assume account equity E=$100; risk budget r=0.25% or 0.50% of E; 1.00% adverse stop trigger; 0.15% round-trip transaction cost; hypothetical incremental adverse stop gap/slippage g. No funding (must be added when observed). All percentages are of position notional; entry slippage must also be included in a true replay.

Conservative nominal bound N = E*r/(0.0100 + 0.0015 + g_budget). At g_budget=0.50%: loss/notional 1.65%, N=$15.15 for 0.25% equity risk, N=$30.30 for 0.50% equity risk. These are notional sizes, NOT margin. 25x would require approx $0.61/$1.21 initial margin respectively, before venue-specific minimums and maintenance requirements. The leverage setting does not change stop-loss dollars at fixed notional, but changes liquidation distance and margin requirements.

At N=$30.3030 (sized for 0.5% equity risk and 0.5% gap):

| Actual extra adverse gap | Total stop loss / notional | Loss / equity |
|---:|---:|---:|
| 0.00% | 1.150% | 0.348% |
| 0.50% | 1.650% | 0.500% |
| 1.00% | 2.150% | 0.652% |
| 3.00% | 4.150% | 1.258% |

For a 3% gap stress budget instead, N=$6.02 (0.25% risk) or $12.05 (0.50% risk), using 4.15% stop+cost+gap. This is only a hypothetical stress envelope; even 3% is not a proven maximum gap.

## Direction-specific replay geometry
LOW->LONG: executable entry is ask-side fill after D250 signal and H1 confirmation; protective SELL stop fills at bid-side available depth. HIGH->SHORT: executable entry is bid-side fill; protective BUY stop fills at ask-side depth. In both cases, signal time must precede order placement and fills; maker assumptions require queue evidence. Stop-trigger last price is not guaranteed stop fill; use stop-market depth, latency and mark/liquidation path, and explicitly flag when unavailable. Keep both legs of spread, fees, funding and same-side re-extreme invalidation in chronological event time.

## Consequences for comparison
The 3x/5x historical fixed-exposure terminal equity curves cannot be compared with 0.25%-0.5% risk-sized alternatives without identical 67 trade IDs, UTC event tape, funding/fees/slippage and sequential capital accounting. The previous 61.2% MFE giveback is diagnostic, not proof that a profit-lock overlay works. Previously rejected trailing/flow exits remain rejected. Do not report a liquidation count of zero without a mark-price path and venue maintenance-margin schedule.

## Reproducibility
Python-independent formulas: N=100*r/(0.01+0.0015+g_budget), realized_equity_loss_pct=100*(N/100)*(0.01+0.0015+g_actual). g_budget=.005 for the four-row table, r=.005; g_actual in [0,.005,.01,.03]. Round displayed numbers only after calculation.

## Missing inputs and next execution replay gate
67 matched trade IDs and actual UTC event sequences, May M1 coverage, bid/ask L50 snapshots, public trades, mark-price and funding/fee schedules; verify data provenance and complete intervals before calling any row replay-eligible. Report results separately by LOW/LONG and HIGH/SHORT and chronological month. No new PnL, MTM DD, fills, stops or liquidation observations are claimed here.
