# HYPE D250 frozen-entry risk-budget reconciliation — 2026-11-18 08:34 CET

Research only; **analytical stop-loss stress**, not event-level Bybit execution replay. No orders, no detector training, no threshold changes.

## Source checks
Read on target branch: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, HYPE_EVERY_LOCAL_ROBUST_STRATEGY_2026-11-12.md, HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md, and d250_event_causality_gate_20261118.py.

Frozen D250: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; side-normalized flow15 < 0.4504731635235635. LOW -> LONG; HIGH -> SHORT. The 67-trade baseline assumes 1.00% adverse-price cut and 0.15% round-trip notional costs. It reports 3x exposure $100 -> $531.16, closed DD 18.56%; 5x $100 -> $1,308.86, closed DD 29.36%. These are *not* execution-verified, MTM-verified or prospective live returns.

## New deterministic calculation
Assume a fully filled stop and additive total adverse execution deviation s (including gap/slippage beyond the nominal 1% trigger). Approximate stop-loss fraction of notional = 0.0100 + 0.0015 + s. Risk-based maximum **account notional exposure** = desired equity risk / stop-loss fraction. This is a simplified conservative sizing stress, not a guarantee: gaps, liquidation, fee-tier asymmetry, funding, mark/last differences, and nonlinear fills remain unverified.

| Additional adverse execution deviation | Stop loss/notional | Max exposure at 0.25% equity risk | Max exposure at 0.50% equity risk | Loss at historical 3x exposure | Loss at historical 5x exposure |
|---|---:|---:|---:|---:|---:|
| 0.00% | 1.15% | 0.2174x | 0.4348x | 3.45% | 5.75% |
| 0.10% | 1.25% | 0.2000x | 0.4000x | 3.75% | 6.25% |
| 0.50% | 1.65% | 0.1515x | 0.3030x | 4.95% | 8.25% |
| 2.00% | 3.15% | 0.0794x | 0.1587x | 9.45% | 15.75% |

Calculation checked directly for all four rows using exact arithmetic expressions in this run. The first row exactly reconciles with reported 5x worst modeled trade -5.75% and 3x worst modeled trade -3.45%; **this is a consistency check, not independent validation of the original trade path**.

At $100 equity and 0.5% risk with 0.5% adverse-gap allowance, nominal position <= $30.30; at 0.25% <= $15.15. If 25x instrument leverage is available, initial margin is approximately $1.21 and $0.61 respectively, excluding margin rules and fees. Position notional is constrained by stop-risk, not by available leverage.

## Direction-specific execution geometry
LOW -> LONG: stop is a SELL; an adverse gap is downward and should be measured against executable bid depth and mark-trigger mechanics. HIGH -> SHORT: stop is a BUY; an adverse gap is upward and should be measured against executable ask depth and mark-trigger mechanics. M1 OHLC cannot establish intra-minute order of stop and profit events; missing L50/Public Trades/mark snapshots must not be imputed.

## Implications for the next matched replay
1. Preserve original 67-trade frozen baseline *unchanged* and compare against a **new** risk-budgeted portfolio; never present its 3x/5x return as if it used 0.25–0.5% stop-risk.
2. Reconstruct per-trade UTC anchors, signal time, entry, side, mark price, public trades, bid/ask depth, stop trigger, exit and funding. Reject missing event provenance rather than assume execution.
3. Compare same eligible trade set, same fees/slippage, sequential capital reservation, 0.25% and 0.50% risk and <=1% concurrent stop-risk; show closed and mark-to-market DD separately, monthly net equity, fills/stops, liquidation-distance and MFE.
4. Keep rejected flow/MFE and ATR trailing overlays rejected; opposite-control price-impact efficiency exits remain **unvalidated hypotheses** until truly unseen forward results.

## Evidence status
No individual 67-trade UTC ledger or matched raw event replay was obtained in this iteration. No new actual PnL, monthly equity, observed liquidations, MTM DD or MFE captured can be claimed. The risk frontier is an explicit *scenario*, not a validated safe fill. 
