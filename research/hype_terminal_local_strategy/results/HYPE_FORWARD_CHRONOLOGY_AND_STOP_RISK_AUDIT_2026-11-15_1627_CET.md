# HYPE frozen-entry chronology and executable-risk audit — 2026-11-15 16:27 CET

Research-only; no orders, retraining, threshold changes, or production changes.

## Source read directly from target branch
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `results/HYPE_FROZEN_STOP_EXECUTION_BOUNDARY_2026-11-15_1534_CET.md`
- `strict_execution_provenance_research.py`

## New finding 1: sealed May is NOT chronologically forward of July-August development
The frozen 1% cut was selected using Jul12-Aug07 and Aug08-Sep01, then evaluated on "sealed May", Sep01-Oct01, and Oct04-Nov03. Even if May was held out from tuning, May precedes development in calendar time and is a historical holdout, not forward chronological validation. The Sep and Oct-Nov periods can qualify as later-date holdouts only if no later-date information influenced features, signal selection, stop selection or dataset revisions. Therefore the reported May-to-Nov equity path and its DD cannot be described as a strictly chronological walk-forward result without rebuilding the timeline and state of knowledge. Do not change any reported baseline figures; relabel their evidence status.

## New finding 2: fixed 3x/5x exposure is incompatible with 0.25%-0.5% stop-risk cap
Frozen 1% stop, 0.15% round-trip notional costs. With extra adverse stop fill gap g, risk fraction = exposure*(0.0115+g).
- 3x: g=0 => 3.45% equity; g=0.5% => 4.95%; g=1% => 6.45%.
- 5x: g=0 => 5.75% equity; g=0.5% => 8.25%; g=1% => 10.75%.
At equity risk 0.25%-0.5%, the maximum account notional exposure is:
- g=0: 0.21739x to 0.43478x.
- g=0.5%: 0.15152x to 0.30303x.
- g=1%: 0.11628x to 0.23256x.
For $100 equity and 0.5% risk, g=1% implies $23.26 notional. This is scenario budgeting, NOT a guarantee: stop-market gaps can exceed assumed g. Leverage (25x) only changes posted margin and liquidation mechanics; it cannot substitute for notional risk budgeting. Total simultaneous planned stop-risk <=1% equity, and any candidate trade must pass mark-price liquidation-buffer checks.

## New finding 3: provenance test does not prove event data
`strict_execution_provenance_research.py` hashes files and compares user-declared start/end coverage, but does not parse content for timestamps, role-specific schemas, price/size, exchange order ACK, sequence continuity, bid/ask execution or liquidation mark trajectory. Its self-test uses the same four-byte fixture for all source roles. Status remains unverified execution; do not report zero liquidations.

## Reproducible deterministic checks
```python
cost=.0015; stop=.01
for E in (3,5):
    print(E, [round(100*E*(stop+cost+g),4) for g in (0,.005,.01)])
for g in (0,.005,.01):
    print(g, [round(r/(stop+cost+g),6) for r in (.0025,.005)])
```
Expected:
3 [3.45,4.95,6.45]; 5 [5.75,8.25,10.75]
0 [0.217391,0.434783]; .005 [0.151515,0.30303]; .01 [0.116279,0.232558].

## Blocking data for matched replay
Need immutable per-trade timestamped rows for 67 completed plus four pending episodes; candidate local confirmation availability; side, entry and stop order chronology; actual public trades and L50 orderbook paths, mark/funding, and event sequence coverage. Recovered M1 OHLC alone cannot order within-minute stops and cannot verify fills. Replay must compare untouched 1% baseline to risk-sized variants on identical chronological trades with fees, funding, spread, adverse gaps, capital reuse limits and independently frozen future windows. LOW->LONG and HIGH->SHORT must be reported separately; first causally available opposite local only; reject previously rejected MFE overlays pending independent evidence.

## Status
New source-backed chronological-validity and risk-budget audit completed. No event-level matched trade replay, monthly net equity, verified mark-to-market DD, MFE capture, fills or liquidation count in this iteration. Existing model returns remain historical simulation, not live validation.
