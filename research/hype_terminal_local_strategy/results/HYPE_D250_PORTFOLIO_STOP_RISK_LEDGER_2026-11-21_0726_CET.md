# D250: cross-position risk ledger and liquidation fail-closed test — 2026-11-21 07:26 CET

Research-only continuation. No detector retraining, no production changes, no orders.

## Directly verified sources
Read `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `stop_geometry_risk_gate_20261121.py` from this branch. D250 remains frozen (250m, rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635). The historical 67 trades are still not event-level execution verified.

## New executable arithmetic audit (independent of OHLC and future extrema)
The gate's `max_total_stop_risk` validates only a *single* candidate's `risk_fraction <= max_total_stop_risk`; it never reads existing open positions or reserved stop risk. Hence two accepted candidates each at 0.5% plus a third at 0.5% would produce 1.5% aggregate planned stop-risk, breaching the 1% portfolio ceiling. This is a real code-path deficiency, not a measured Bybit performance claim.

Concrete reproduction: call `gate(Candidate("LONG",100,97,2,80),100,risk_fraction=.005,max_total_stop_risk=.01)` three times; each returns PAPER_ELIGIBLE, each reserves $0.50 of modeled loss, total $1.50 > $1.00 allowed. Position notional per call $15.873015873; total $47.619047619, and 25x initial margin total $1.904761905. Separate direction/asset signals cannot reuse the same risk budget while earlier trades remain OPEN or UNRESOLVED.

The gate also takes a user-supplied liquidation price and validates only its relative location; it does not calculate account-level maintenance margin, funding accrual, cross-margin interaction, changing equity, other positions, or exchange-specific liquidation mechanics. PAPER_ELIGIBLE must never be interpreted as live eligible.

## Required deterministic portfolio gate before any new paper entry
1. Maintain an append-only ledger with event-time and availability-time for each fill, fee, funding charge, stop order, close, cancel, liquidation update, and gap; reserve risk at order acceptance, not just fill.
2. `available_stop_budget = max(0, .01 * conservative_current_equity - sum(open_or_pending_reserved_worst_case_loss))`. Treat OPEN/UNRESOLVED as consuming budget. Recompute when equity falls; do not assume closed-equity equals MTM equity.
3. For candidate risk .5% of equity, reject a third simultaneous .5% candidate when two already consume 1%. Do not recycle budget until an exit fill is confirmed, not merely when an opposite-local signal fires.
4. Risk reservation must include fees, adverse gap and estimated funding, but a fixed gap reserve is only a scenario allowance, never a hard bound. Stress the full portfolio under common correlated gaps; cap notional and margin separately.
5. Keep original 1% cut + hold-to-causal-opposite-local baseline unchanged; staged entries/profit locks remain unpromoted until a same-sample cost-parity replay on real time-ordered quotes.

## Reproduction with standard Python
```python
equity=100.0
per_trade_risk=.005*equity
limit=.01*equity
reserved=0.0
for i in range(3):
    accepted=reserved+per_trade_risk<=limit+1e-12
    print(i+1,accepted,round(reserved,2))
    if accepted: reserved+=per_trade_risk
assert reserved==1.0
```
Expected: (1, True, 0.0), (2, True, 0.5), (3, False, 1.0).

## What is NOT established
No matched 67-trade UTC Public Trades/L50/Mark Price execution replay was performed in this checkpoint. No new monthly net equity, MTM DD, stop fills, liquidation count, forward PnL or MFE retention claims. Need per-trade event IDs and continuous quote/mark/funding coverage first. This is a portfolio risk-gate audit, not a new trading edge.
