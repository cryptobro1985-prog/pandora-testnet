# HYPE post-local execution provenance and gap-risk checkpoint — 2026-11-16 23:26 CET

Research-only. Existing frozen D250 unchanged. No orders or production changes.

## New code-path audit (read directly from branch)
- `trade_manifest_gate_research.py` demands `entry_fill_source`, `exit_fill_source`, `protective_stop_order_source`, `event_sequence_source` and other sources, but checks only whether their strings are nonempty. A string `"private-fill"` does not authenticate a real fill. Its self-tests use entirely synthetic rows.
- A historical *paper* replay cannot supply authentic private fill logs for trades never submitted. Therefore requiring private fills as a prerequisite for all historical simulations confuses two valid evidence classes: **MODELED_EXECUTION** (event-driven reconstruction with explicit assumptions) versus **VERIFIED_EXCHANGE_FILL** (actual private order records). Neither class may be relabeled as the other.
- `stop_risk_budget_replay_20261116.py` uses `distance + 0.0015 round-trip fees + 0.0006 funding reserve + 0.01 gap reserve` to size both LONG and SHORT, then stresses realized gaps. This is a risk-scenario calculation, not an event replay. A 1% gap reserve is **not** a guaranteed loss cap.
- Existing recovered artifact continuity report documents 157,375 M1 rows and five missing interior minutes, but these are not matched to 67 immutable trade IDs. Do not fabricate those IDs or fill timestamps.

## Fresh exact deterministic stress computation
For fixed 1% adverse-price stop, 0.15% round-trip fee, 0.06% funding reserve, 1% gap reserve, equity $100:
`notional = equity * risk_fraction / (0.01+0.0015+0.0006+0.01)`.
Scenario realized loss = `notional*(0.01+0.0015+0.0006+realized_gap)`.
These are *assumptions*, not empirical fills or a mark-price liquidation check.

| Extra adverse gap | Loss as % equity (risk budget 0.25%) | Loss as % equity (risk budget 0.5%) |
|---:|---:|---:|
| 0% | 0.1369% | 0.2738% |
| 1% | 0.25% | 0.5% |
| 3% | 0.4762% | 0.9525% |
| 5% | 0.7025% | 1.405% |

At 5% additional gap the nominal 0.5% risk budget experiences modeled 1.405% equity loss; isolated 25x margin is about 4% of notional before maintenance and fees, so liquidation may precede the hypothetical stop fill. Do not report 1.405% as a verified executable loss in isolated margin.

## Required correction to research evidence taxonomy (not a production change)
1. Preserve original 67-trade baseline and D250 thresholds; recover immutable signal/trade ledger and timestamps before comparing policies.
2. Emit `MODELED_EXECUTION`, `EXCHANGE_VERIFIED`, `UNKNOWN_COVERAGE`, or `REJECT_LOOKAHEAD` separately. The historical paper replay may be modeled with real timestamped M1/trades/mark/L50 tape and conservative slippage; exchange-verified requires actual private fill IDs, which do not exist for hypothetical trades.
3. Source fields need verified provenance (artifact ID/hash, exact time coverage, event type), not merely nonempty strings. Missing mark/L50/stop sequencing => UNKNOWN, never zero liquidations.
4. Per trade report H1 LOW/LONG or HIGH/SHORT, confirmed signal time, adverse move before entry, stop and notional, mark-vs-stop precedence, cost/funding, MFE, causal opposite-local exit and overlap accounting. Mark missing M1 minutes UNKNOWN.
5. Only after same-ID event replay compare baseline, risk 0.25%-0.5%, staged entry, break-even/profit lock; rejected overlays remain rejected without independent forward evidence.

## Reproducibility
```python
for risk in (.0025,.005):
    n=100*risk/(.01+.0015+.0006+.01)
    for gap in (0,.01,.03,.05):
        print(risk,gap,round(100*n*(.01+.0015+.0006+gap)/100,4))
```
No new claim of actual trade outcomes, monthly equity, MTM drawdown, MFE improvement, fill count or liquidation count. This iteration is a new audit of existing execution validation code plus deterministic stress calculation, not the requested full matched event replay.
