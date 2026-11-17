# D250 geometric friction stress test — 2026-11-17 22:29 CET

Research only; NO execution replay, NO retraining, NO live orders.

## Verified inputs
Fetched existing frozen reports directly from `research/hype_terminal_local_strategy/results/` on the requested branch:
- `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 71 accepted; 67 completed opposite-local episodes; D250 unchanged.
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential trades; starting $100; ending $531.16 (3x), $848.72 (4x), $1308.86 (5x), with 0.15% notional round-trip cost already assumed.
- `HYPE_D250_67_TRADE_BREAK_EVEN_COST_BOUND_2026-11-17_2135_CET.md`: 0.9513% additional notional cost arithmetic-mean threshold at 5x, based on rounded average win/loss.

## NEW calculation: multiplicative equity haircut sensitivity
Unlike arithmetic mean, compound capital depends on geometric returns. Without individual trade outcomes, a useful **stylized** stress model applies the same fractional equity haircut `h` AFTER each of 67 simulated trades. Then `E_stressed=E_original*(1-h)^67`; solve `E_stressed=100`:
`h*=1-(100/E_original)^(1/67)`.

| Exposure | Published end equity | Mean log growth per trade | Break-even uniform equity haircut per trade | Equity haircut divided by exposure (notional-equivalent approximation) |
|---|---:|---:|---:|---:|
| 3x | $531.16 | 2.4924% | 2.4616% | 0.8205% |
| 4x | $848.72 | 3.1919% | 3.1415% | 0.7854% |
| 5x | $1308.86 | 3.8384% | 3.7657% | 0.7531% |

At 5x, the 0.7531% *notional-equivalent approximation* is lower than the previously reported 0.9513% arithmetic-mean bound. This illustrates why average returns can overstate friction tolerance of compounded capital.

**Critical distinction:** a fixed extra fee/slippage of `c` on trade notional subtracts `exposure*c` from each trade's realized equity return BEFORE compounding, not a uniform multiplicative haircut after it. Consequently the table is NOT an exact execution-cost break-even and must NOT be used as a trading slippage budget. Exact answer requires the missing 67 individual ordered trade returns, executions, and path-dependent stops. No interpolation of missing trades.

## Reproduce (Python standard library)
```python
from math import log
for x, final in [(3,531.16),(4,848.72),(5,1308.86)]:
    h=1-(100/final)**(1/67)
    print(x, 100*log(final/100)/67, 100*h, 100*h/x)
```

## Next indispensable step
Recover original 71 signal timestamps / 67 executed-or-finalized episodes from source artifacts. Do NOT infer fills from summary tables. For each LOW->LONG and HIGH->SHORT, record signal availability UTC, next executable price, intrabar uncertainty, mark-price stop trigger, bid/ask fill, fee/funding, gap/slippage, liquidation buffer, K2 opposite-local availability, and causal MFE path. Keep rejected overlays rejected. Compare on matched chronological episodes and unseen forward with frozen thresholds. If raw ledger cannot be recovered, label replay blocked rather than synthesize it.

Status: independent new aggregate geometric stress analysis completed; historical per-trade replay and MTM DD not verified.
