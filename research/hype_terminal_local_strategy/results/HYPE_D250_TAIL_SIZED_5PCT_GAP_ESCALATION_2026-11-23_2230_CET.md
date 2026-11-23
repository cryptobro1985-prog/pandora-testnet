# D250: 2% tail-sized positions under a 5% execution gap — 2026-11-23 22:30 CET

Research only. Continuation of HYPE_D250_CONCURRENT_TAIL_RISK_BUDGET_2026-11-23_2126_CET.md. This is a **new deterministic stress calculation**, not a Bybit event replay or verified exchange fill. Frozen D250, original baseline, rejected MFE overlays and production remain unchanged. No orders.

## Specific question
If positions are sized to lose 0.25% or 0.50% of $100 equity at a 2% additional adverse stop-execution gap, what happens if the actual additional gap is 5%? Does the 2%-tail sizing guarantee the risk budget? **No.** The 5% gap exceeds the modeled per-trade budget in every tested case.

## Assumptions and exact arithmetic
Entry reference 100; entry adverse slippage 0.03%; stop execution slippage 0.05%; fee 0.075% of entry and exit notional each; entry-relative stop distances 1% and 3.14%; 2% extra adverse gap used for position sizing; 5% extra gap for new stress. Long entry=100*(1+0.0003), short entry=100*(1-0.0003). Stop fill = 100*(1-sign*stop_distance)*(1-sign*(0.0005+gap)), sign +1 long / -1 short. Loss fraction of entry notional = [sign*(entry-fill)+0.00075*(entry+fill)]/entry. Nominal = planned dollar risk / loss_fraction(2% gap). 25x margin is nominal/25 only; liquidation and maintenance-margin distances are **not** validated.

| Side | Stop | Budget | Nominal sized to 2% gap | Margin at 25x | Loss at 5% gap |
|---|---:|---:|---:|---:|---:|
| LOW→LONG | 1% | $0.25 | $7.7972 | $0.3119 | $0.48133 |
| HIGH→SHORT | 1% | $0.25 | $7.6834 | $0.3073 | $0.48305 |
| LOW→LONG | 3.14% | $0.25 | $4.7168 | $0.1887 | $0.38692 |
| HIGH→SHORT | 3.14% | $0.25 | $4.5957 | $0.1838 | $0.39235 |
| LOW→LONG | 1% | $0.50 | $15.5944 | $0.6238 | $0.96267 |
| HIGH→SHORT | 1% | $0.50 | $15.3669 | $0.6147 | $0.96610 |
| LOW→LONG | 3.14% | $0.50 | $9.4336 | $0.3773 | $0.77383 |
| HIGH→SHORT | 3.14% | $0.50 | $9.1913 | $0.3677 | $0.78470 |

Two simultaneous 0.25%-budget positions (one LONG, one SHORT) under the 5% gap jointly lose **$0.96438** with 1% stops or **$0.77927** with 3.14% stops. Two simultaneous 0.50%-budget positions jointly lose **$1.92877** with 1% stops or **$1.55853** with 3.14% stops, violating the 1% total stop-risk target under this stress. Joint event frequency is unknown.

## Reproduction (Python 3 stdlib)
```python
for sign, side in ((1, "LOW->LONG"), (-1, "HIGH->SHORT")):
    for d in (0.01, 0.0314):
        entry = 100 * (1 + sign * 0.0003)
        def loss_fraction(gap):
            fill = 100 * (1 - sign * d) * (1 - sign * (0.0005 + gap))
            return (sign * (entry - fill) + 0.00075 * (entry + fill)) / entry
        for budget in (0.25, 0.50):
            nominal = budget / loss_fraction(0.02)
            print(side, d, budget, round(nominal, 4),
                  round(nominal / 25, 4), round(nominal * loss_fraction(0.05), 5))
```

## Interpretation and hard evidence boundary
This calculation is a **stress escalation**, not a new signal or optimized stop. It demonstrates that a 2%-gap tail-budget is a conditional scenario, not a hard loss guarantee. The earlier 1% cut remains a frozen research candidate, not a promoted live rule. Do not infer an absence of liquidation from the small isolated-position margin; mark price, maintenance margin, isolated/cross configuration, stop trigger, order acknowledgment and executable liquidity must be verified. The low nominal sizes may fail exchange minimum-order constraints. No 71-trade matched historical replay, fill count, net equity, MTM drawdown, liquidation count or independent forward improvement is claimed.

## Next required empirical work
Recover immutable 71-entry cohort and per-signal timestamped Bybit Public Trades / bid-ask / L50 / mark-price / OI / liquidations where genuinely present. Match local-availability time to order-send and executable fill; separately replay LOW→LONG and HIGH→SHORT. Preserve original baseline and identical cost/funding/slippage across stop variants. Record per-trade stop trigger/fill gaps, mark-price liquidation sequence, MFE and opposite-control-transfer exits. Until the actual gap distribution and minimum tradeability are known, **do not promote the 2% or 5% stress assumption into a live risk guarantee**.
