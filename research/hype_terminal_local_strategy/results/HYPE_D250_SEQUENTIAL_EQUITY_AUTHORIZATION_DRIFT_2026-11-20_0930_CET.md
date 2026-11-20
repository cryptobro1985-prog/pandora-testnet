# D250 sequential equity authorization drift — 2026-11-20 09:30 CET

Research-only. No changes to detector, thresholds, production, or orders.

## Source inspected
- `research/hype_terminal_local_strategy/portfolio_accounting_failclosed_gate_20261120.py`
- `research/hype_terminal_local_strategy/portfolio_accounting_research.py`
- frozen D250 and asymmetric-risk reports (2026-11-12).

## New reproducible counterexample (mathematical replay of accounting, NOT historical Bybit fills)
The current gate checks `account_exposure == authorized_notional / entry_equity` and `authorized_stress_loss <= entry_equity * risk_budget_fraction` **within each caller-supplied trade**, but does not compare `entry_equity` with actual running portfolio equity. The downstream evaluator compounds actual equity using the supplied exposure. Therefore stale authorization equity can pass while the purported cash loss budget becomes wrong.

Take 100 sequential non-overlapping synthetic LONG trades. Every trade is authorized against stale `entry_equity=$100`, with `authorized_notional=$50`, `account_exposure=0.5`, `authorized_stress_loss=$0.50`, `risk_budget_fraction=0.005`. Each has `underlying_return_fraction=-0.01`, `roundtrip_cost_fraction=0`, `funding_fraction=0` (explicit synthetic zeros). Each trade passes the existing local checks, yet each removes 0.5% of **actual** equity, not $0.50. After 100 trades actual equity is `100*(0.995)^100 = $60.577...`. This example by itself does not violate actual 0.5% risk because the downstream evaluator uses fixed 0.5x exposure, but it shows that `authorized_notional=$50` is NOT what the evaluator is actually trading: the 100th modeled notional is about $30.44. The claimed notional and fills are therefore disconnected.

More serious counterexample: set `account_exposure=1`, `authorized_notional=$100`, `entry_equity=$100`, `authorized_stress_loss=$0.50`, `risk_budget_fraction=0.005`, with a **1% adverse** price return. The gate accepts the arbitrary $0.50 stress-loss declaration, while the actual scenario loss is $1.00 (1% of capital), double the risk budget. This does not require sequential drift. The gate never recomputes stress loss from price stop, fees, slippage and notional. Funding is merely supplied by caller; its presence does not verify provenance.

## Reproduction
```python
from research.hype_terminal_local_strategy.portfolio_accounting_failclosed_gate_20261120 import checked_evaluate
t=dict(trade_id="synthetic", entry_ts_ms=1000, exit_ts_ms=2000, side="LONG",
       underlying_return_fraction=-.01, account_exposure=1.,
       roundtrip_cost_fraction=0., funding_fraction=0.,
       authorized_notional=100., entry_equity=100.,
       authorized_stress_loss=.5, risk_budget_fraction=.005)
r=checked_evaluate([t])
assert r["status"] == "SCENARIO_CLOSED_ONLY_NOT_EXECUTION_VERIFIED"
assert r["closed_accounting"]["end_equity"] == 99.
# 1% equity loss while risk authorization claims only 0.5%.
```

## Correct fail-closed next gate
1. Recompute stop-risk independently from signed stop price, fill side, adverse-gap stress, fees, funding reserve, and executable notional; never trust `authorized_stress_loss`.
2. Match each trade's authorized `entry_equity` to running **pre-entry** equity (after all prior realized PnL and funding), and require `authorized_notional` to equal modeled actual position notional.
3. Enforce total open stop-risk <=1% of current equity and single-trade stress risk <=0.25–0.5% using the same price/fill assumptions as the replay.
4. Treat unverified funding, mark-price path, L50 fills and maintenance margin as UNKNOWN, not zero or no-liquidations.
5. Preserve unchanged baseline; no previously rejected MFE overlay promoted. No new performance claim.

## Evidence status
This is a code-grounded counterexample with synthetic accounting, **not** a Bybit historical matched trade replay. No new independently verified trades, monthly MTM DD, liquidation count, or MFE retention. The 67-trade timestamped execution tape remains required.
