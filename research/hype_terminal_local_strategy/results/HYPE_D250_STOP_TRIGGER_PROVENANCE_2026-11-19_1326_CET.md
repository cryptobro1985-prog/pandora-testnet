# HYPE D250 stop trigger provenance audit — 2026-11-19 13:26 CET

Research only. Existing branch, no detector retraining, production changes or orders.

## Source inspection
Read frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `quote_event_stop_replay_research.py`, and latest quote-gap audit from this branch. D250 entry thresholds remain untouched. The replay currently triggers STOP from executable bid (LONG) / ask (SHORT), and stores mark only as output metadata. It does not declare whether the simulated exchange stop was configured to trigger on LastPrice, MarkPrice or IndexPrice. Consequently the same historical path can yield different stop times even with complete quotes.

## Four executed deterministic counterexamples
All calculations evaluated on 2026-11-19. Entry 100, stop 1%, no execution/funding assumptions:
| Side | Bid | Ask | Mark | Stop | Bid/ask trigger | Mark trigger |
|---|---:|---:|---:|---:|---|---|
| LONG | 99.4 | 99.6 | 98.7 | 99 | false | true |
| SHORT | 100.4 | 100.6 | 101.4 | 101 | false | true |
| LONG | 98.8 | 99.0 | 99.5 | 99 | true | false |
| SHORT | 101.0 | 101.2 | 100.5 | 101 | true | false |

4/4 demonstrate a disagreement; these are adversarial synthetic examples, NOT observed Bybit trades. Trigger price and executable fill price must be modeled separately. Bid/ask can be a hypothetical fill reference, but is not a substitute for exchange stop trigger source. Mark-only crossing does not prove a fill, and bid/ask crossing does not prove a mark-triggered stop.

## Required matched-trade replay
1. For each of the frozen 67 D250 entries, record UTC entry availability, actual hypothetical bid/ask entry, stop order trigger source, order activation time, quantity, stop price and tick-size rounding.
2. Stream trigger-source events and executable quotes in timestamp order; report quote/mark gaps and stale books separately. Trigger at first eligible event, then model stop-market executable fill with L50 depth and slippage; no fills across missing data.
3. Track mark-price margin/liquidation separately from stop trigger and report unresolved cases rather than zero liquidations. Model maintenance margin, funding, fees and portfolio equity/available margin.
4. Compare original baseline unchanged against risk-sized 0.25%-0.5% equity, aggregate stop risk <=1%, same sequential events/costs, no overlapping capital; independent forward held out.
5. Report LOW->LONG and HIGH->SHORT separately, monthly net equity, MTM/closed DD, MFE capture/giveback, stop and liquidation counts, fills, gap/unresolved counts.
6. Do not promote rejected MFE protection overlays absent genuinely new independent evidence.

## Status
Executed 4 synthetic stop-trigger counterexamples. No 67-trade historical replay or verified net PnL, fills, MTM DD, liquidation counts or forward performance. Frozen D250 unchanged.
