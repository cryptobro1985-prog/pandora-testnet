# HYPE D250 checkpoint — 2026-11-18 21:26 CET: stop-gap risk-budget stress

## Scope
Research-only deterministic risk arithmetic for **post-confirmed** H1 LOW→LONG and H1 HIGH→SHORT. No detector retraining, no snapshot classification, no real orders, no changed frozen thresholds. This is **not** an event replay or an empirical slippage estimate.

## New reproducible stress calculation
Use equity E=$100; initial maximum planned loss r=0.5% of equity ($0.50); adverse-price stop distance d=1%; total fee allowance f=0.15% of notional; adverse funding reserve u=0.09%; assumed stop gap/slippage reserve s0=0.5%. All cost inputs here are **scenarios, not observed Bybit costs**.

Planned notional N=E*r/(d+f+u+s0) = 0.50/0.0174 = **$28.73563218** (0.28736x equity exposure). This calculation is symmetric in *percentage distance* for LONG and SHORT, but actual stop trigger, bid/ask execution and liquidation distances are **not** symmetric and require per-side event data.

Holding N fixed, if realized gap/slippage exceeds the planning reserve:

| Realized gap/slippage (% of notional) | Total modeled loss ($) | Equity loss |
|---:|---:|---:|
| 0.50% | 0.5000 | 0.500% |
| 1.00% | 0.6437 | 0.644% |
| 1.50% | 0.7874 | 0.787% |
| 3.00% | 1.2184 | 1.218% |

Reproduce: `N=100*.005/(.01+.0015+.0009+.005)`; `loss=N*(.01+.0015+.0009+realized_slippage)`. The last row breaches the *1% aggregate stop-risk cap* even for a single position, despite a 0.5% planned-risk sizing rule. Stop orders cannot guarantee a maximum loss through price gaps, outages, partial fills or liquidations. This is a **tail-risk sensitivity** rather than a probabilistic estimate.

## Decision for trade replay
1. Keep unchanged baseline and fixed D250 entries on identical chronological sample. Require side-specific confirmed event timestamp, order submission/fill timestamps, stop trigger source, mark and bid/ask tape, funding events, opposite-local event ledger and capital occupancy.
2. Evaluate LONG→sell-stop at bid and SHORT→buy-stop at ask separately; measure adverse excursion between H1 extreme and causal confirmation, then between confirmation and actual fill. If L50 is missing, label execution **unverified** rather than invent spread or depth.
3. Compute risk notional from **effective worst-case modeled loss** including round-trip fees, observed adverse funding and scenario stop gaps. Enforce total planned open stop-risk <=1% equity and no overlapping capital reuse. Report realized losses beyond budget separately, not as compliance.
4. Before claiming no liquidations, calculate isolated/cross margin assumptions and liquidation thresholds from contemporaneous exchange rules, actual mark paths, and fees. A nominal 25x leverage choice does not establish a safe liquidation distance.
5. Test staged entry and profit protection only on the same event-complete cohort; previously rejected MFE overlays remain rejected without new independent forward evidence. For opposite-local exits, use **confirmation timestamp**, not future opposite extreme.

## Evidence limits
This run inspected the current branch's `d250_trade_replay_manifest_gate.py` and prior interval-gate checkpoint. The existing gate only checks eligibility assertions; it does not verify fills, actual stop prices, position sizing, or mark-to-market. Original May-inclusive 67-trade UTC journal and independently matched Bybit Public Trades/L50/mark/funding remain unverified. Therefore **no new net PnL, monthly equity, MTM DD, MFE capture, liquidation count, or unseen forward performance** is reported. Frozen D250 thresholds remain unchanged.

Next concrete work: run existing `test_d250_ledger_window.py` in an executable checkout/CI; obtain independently sourced trade/event ledgers and implement side-specific cost-aware fill replay before comparing strategies.
