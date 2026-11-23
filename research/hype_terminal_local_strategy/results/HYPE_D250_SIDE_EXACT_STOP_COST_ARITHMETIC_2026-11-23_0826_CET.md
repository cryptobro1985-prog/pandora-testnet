# D250 exact-side stop execution arithmetic audit — 2026-11-23 08:26 CET

Research only. No detector retraining, no threshold changes, no production edits or orders. Source inspected directly on branch: `research/hype_terminal_local_strategy/d250_cost_aware_risk_gate.py` and frozen `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`. This is a **new deterministic accounting regression**, NOT matched Bybit execution replay.

## Finding

Current sizing gate approximates the loss fraction identically for LONG and SHORT as `abs(entry-stop)/entry + fee_entry + fee_exit + slip_entry + slip_stop + gap_stop`. This adds price execution percentages at entry and stop without applying them to the respective execution prices. It also charges exit fee on entry notional, rather than actual exit notional. Under directional adverse stop gaps, LONG and SHORT have different exact loss fractions, so symmetric approximate sizing can **under-reserve SHORT stop risk**.

For one unit of asset and entry reference E, structural stop S:
- LONG: entry fill = E(1+entry_slip), stop fill = S(1-stop_slip-gap); cash loss = (entry fill - stop fill) + fee_entry * entry fill + fee_exit * stop fill.
- SHORT: entry fill = E(1-entry_slip), stop fill = S(1+stop_slip+gap); cash loss = (stop fill - entry fill) + fee_entry * entry fill + fee_exit * stop fill.
- Divide each by reference E for a per-reference-notional loss fraction. All prices positive; this is a scenario, not guaranteed stop fill.
- Mark-trigger/liq precedence, funding and actual quote-side fill are **not modeled** here.

## Reproduced arithmetic

Scenario (NOT historical Bybit quotes): E=100, LONG stop=99, SHORT stop=101, entry slip=0.03%, stop slip=0.05%, adverse gap=1.00%, taker fee each side=0.06%, equity=$100, stop-risk budget=$0.50.

| Side | Entry fill | Stop fill | Exact modeled loss / $100 reference notional | Existing approximate loss fraction | Exact risk-budget notional | Approximate risk-budget notional |
|---|---:|---:|---:|---:|---:|---:|
| LOW→LONG | 100.0300 | 97.9605 | 2.1882943% | 2.2000000% | $22.84885 | $22.72727 |
| HIGH→SHORT | 99.9700 | 102.0605 | 2.2117183% | 2.2000000% | $22.60686 | $22.72727 |

For SHORT, using the approximate $22.72727 reference notional incurs $0.50266 under this exact scenario, breaching the intended $0.50 risk budget by about $0.00266 (0.53%). Small here but systematic and potentially worse for wider stops/gaps. LONG approximation is conservative for this scenario. No claim that real stop losses are bounded by either value.

## Reproduction

```python
E=100.; fee=.0006; slip_in=.0003; slip_stop=.0005; gap=.01
for side,S in [('LONG',99.),('SHORT',101.)]:
    pin=E*(1+slip_in if side=='LONG' else 1-slip_in)
    pout=S*(1-slip_stop-gap if side=='LONG' else 1+slip_stop+gap)
    price_loss=(pin-pout if side=='LONG' else pout-pin)
    exact=(price_loss+fee*(pin+pout))/E
    approx=abs(E-S)/E+slip_in+slip_stop+gap+2*fee
    print(side,round(exact,9),round(approx,9),round(.5/exact,5),round(.5/approx,5))
```

## Consequence for full cohort replay

Keep the frozen 67-trade baseline unchanged. For prospective alternative risk sizing, compute actual per-side stop loss using bid/ask and executable mark-trigger paths, entry/exit notional fees, funding and maintenance tiers. The 0.25–0.5% equity risk and 1% aggregate cap must apply to **exact scenario or conservative worst-case cash loss**, not the simplified percentage sum. Fail closed if executable event tape is absent. Do not promote a profit-lock overlay on this result.

The 71 accepted D250 signals are not an immutable fill ledger; 67 finalized opposite-local outcomes are not verified executions. Therefore monthly net equity, MTM/closed DD, actual fills/stops/liquidations, MFE captured and unseen forward performance remain UNKNOWN. No real orders.
