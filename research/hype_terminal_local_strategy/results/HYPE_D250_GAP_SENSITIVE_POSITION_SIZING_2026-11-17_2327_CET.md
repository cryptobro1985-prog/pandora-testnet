# D250 gap-sensitive stop-risk sizing — 2026-11-17 23:27 CET

Research only; no new detector, no live orders, no per-trade replay. This is a NEW deterministic risk-envelope stress test based on the frozen entry and published stop report, not historical execution evidence.

## Sources verified on the existing branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: D250 frozen; 71 accepted, 67 finalized, 50/50 OOS; median MAE -0.414%, worst -1.958%; median structural diagnostic stop 3.140% from entry; 61.2% median MFE giveback.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: development-selected 1% adverse price cut, 0.15% assumed round trip fee, 22 fixed-cut exits / 67 trades, 3x $531.16 and 5x $1308.86; closed DD only. These are not verified fills.
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md: sustained opposite price-impact efficiency/control transfer is necessary; raw counter-flow is insufficient; no rejected overlay is promoted.

## New calculation: risk-based sizing under adverse stop execution
Let equity E=$100; fixed stop-price displacement s=1.00% of entry; fee round-trip f=0.15% of notional (source assumption); extra ordinary slippage q=0.10% of notional (stress assumption, NOT observed); adverse gap beyond stop g is varied. First-order worst-scenario loss per unit notional is d=s+f+q+g. Position notional N <= E*r/d where r is target equity risk (fraction); initial margin at instrument leverage 25x is N/25. No guarantee that g cannot exceed a chosen scenario. Funding, tiered maintenance margin, stop trigger mark/last divergence, partial fills, liquidation fees and dynamic equity are not modeled; hence this is not a liquidation certificate.

| Adverse gap beyond stop | Loss per notional | N at 0.25% risk | 25x margin | N at 0.50% risk | 25x margin |
|---|---:|---:|---:|---:|---:|
| 0.00% | 1.25% | $20.00 | $0.80 | $40.00 | $1.60 |
| 0.25% | 1.50% | $16.67 | $0.67 | $33.33 | $1.33 |
| 0.50% | 1.75% | $14.29 | $0.57 | $28.57 | $1.14 |
| 1.00% | 2.25% | $11.11 | $0.44 | $22.22 | $0.89 |
| 2.00% | 3.25% | $7.69 | $0.31 | $15.38 | $0.62 |

For example, a 0.5%-risk position sized using zero-gap assumptions ($40 notional) loses $0.70 (0.70% equity), not $0.50, if gap is 0.5% beyond the stop. At a 2% gap it loses $1.30 (1.30% equity), violating the portfolio's 1% aggregate stop-risk budget even with only one trade. Therefore a static 1% stop alone does not establish the risk ceiling. Risk-based sizing requires explicit gap scenario plus real market minimum notional/quantity and mark-price/liquidation checks; if not feasible, skip the trade, never increase risk to meet minimum order size.

## LOW/LONG and HIGH/SHORT execution geometry (same risk equation, different adverse side)
- LOW -> LONG: confirmation timestamp must precede entry; stop sell can gap downward, best bid and stop-market sell depth determine exit; price crossing the stop within the same M1 candle without tick ordering is ambiguous.
- HIGH -> SHORT: confirmation timestamp must precede entry; stop buy can gap upward, best ask and stop-market buy depth determine exit; mark-price stop trigger and last-trade prints can disagree.
- On both: actual liquidation price must be beyond the stop by a positive buffer under the exchange's applicable maintenance margin schedule and stressed mark/basis moves. Instrument 25x does not imply account exposure 25x: notional here is only ~0.077x-0.4x equity.
- Structural diagnostic stop ~3.14% median distance cannot be substituted with the 1% fixed cut without changing stop-hit distribution. Published 22/67 stop exits are simulated and cannot be promoted as exchange fills.

## Replay acceptance gates
(1) Recover immutable 71 signal UTC timestamps and 67 matched episode IDs; distinguish four censored/unfinalized.
(2) For each direction use first post-confirmation executable bid/ask, not entry candle open unless timestamp aligns; preserve uncertain M1 intrabar order.
(3) Use real Bybit mark-price stop triggers, order-book depth/prints for gap fill and fees/funding; report unknown where absent.
(4) Compute sequential no-overlap equity and mark-to-market DD, monthly net, stop fills, stop-to-liquidation buffer, MFE retention and true unseen forward. Keep frozen D250 and rejected MFE overlays unchanged.

## Reproduction
```python
E=100.0
for g in (0,0.25,0.5,1,2):
    d=(1+0.15+0.10+g)/100
    print(g, round(d*100,2), *[(round(E*r/100/d,2),round(E*r/100/d/25,2)) for r in (0.25,0.5)])
```

Status: reproducible new deterministic risk stress completed; NOT a new matched historical replay. No new net PnL, liquidation count, MTM DD or MFE-capture claim.
