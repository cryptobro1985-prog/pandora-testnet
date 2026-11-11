# HYPE Terminal H1 Local Strategy Contract

## Objective
Build one automatic historical-to-forward detector that decides whether a **major terminal H1 Local LOW/HIGH** has formed. Do not optimize for every small H1 wiggle.

Trading semantics under study:
- confirmed terminal LOW -> LONG bias until the opposite terminal HIGH;
- confirmed terminal HIGH -> SHORT bias until the opposite terminal LOW;
- same-side stronger extreme before opposite confirmation means the prior candidate was not terminal.

## Teacher / target
Primary teacher: STRICT H1 L6/K2 terminal-finalized locals only.
INTERNAL L3/K1 may be retained only as negative/tactical context and must never redefine the core target.

## Historical evidence to collect
For selected strong Sep-Oct 2026 windows, recover every genuinely available historical Bybit stream:
1. executed trades and aggressor flow;
2. L50 order book state and causal replay;
3. book imbalance/depth;
4. replenishment/removal/cancellation/absorption proxies;
5. public liquidations, side, size, notional, burst and exhaustion;
6. open interest and OI delta/notional;
7. mark/index price, basis, funding;
8. M1/M3/M5/H1 price path and response;
9. 60m/6h/24h structural position;
10. candidate survival / same-side invalidation;
11. price-impact efficiency of continuation side;
12. counter-side efficiency / transfer.

Never encode unavailable historical streams as zero. Keep validity/availability masks.

## Main signature hypothesis
STRUCTURAL EXTREME
-> CONTINUATION SIDE LOSES PRICE-IMPACT EFFICIENCY
-> OPPOSITE SIDE GAINS RESPONSE/EFFICIENCY
-> LIQUIDATION PRESSURE EXHAUSTS
-> L50 LIQUIDITY TRANSFERS / ABSORBS
-> PRICE FAILS TO EXTEND SAME-SIDE
-> TERMINAL LOCAL CONFIDENCE RISES

LOW and HIGH must be modeled separately.

## Validation objective
Primary metric is first accepted signal per completed strict swing.
Report:
- TP / FP and first-signal precision;
- recall/coverage;
- distance from true extreme;
- latency;
- MAE before move;
- remaining swing capture;
- performance by period/regime.

No future/teacher field may enter predictive features.
No historical 100% result may be treated as a future guarantee.
