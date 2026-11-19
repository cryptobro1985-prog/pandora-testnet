# HYPE D250 — structural-stop versus fixed-cut risk sizing sensitivity (2026-11-20 00:30 CET)

Research-only, no detector retraining, threshold change, production edit or real orders.

## Sources inspected directly on the requested branch
- `research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
- `research/hype_terminal_local_strategy/results/HYPE_D250_BASELINE_PERIOD_RISK_BUDGET_2026-11-19_2330_CET.md`

## New deterministic calculation: stop geometry is the dominant sizing variable
D250 report: median *diagnostic structural* stop distance from entry 3.140% price, median MAE 0.414%, worst observed MAE 1.958% across 67 completed trajectories. Asymmetric risk report: development-selected fixed 1.0% adverse cut, 22 of 67 fixed-cut exits. These are **different stop policies**. A 1% cut cannot be interpreted as the structural invalidation price, and the 67 completed trajectories cannot be assumed to have all survived a 1% stop.

For comparison only, use the same frozen nominal round-trip cost assumption 0.15% of entry notional, *zero additional* funding/slippage/gap, no liquidation, and one $100 account. For an adverse stop distance d%, maximum nominal dollars = $100 * risk_budget_percent / (d + 0.15), where both percentages are expressed in percentage points. These are arithmetic sensitivity cases, **not** measured stop distributions or tradable sizing recommendations.

| Assumed adverse exit distance | Nominal at 0.25% equity risk | Nominal at 0.50% equity risk | Account exposure at 0.50% |
|---|---:|---:|---:|
| fixed 1.000% cut | $21.74 | $43.48 | 0.4348x |
| observed worst MAE 1.958% (NOT a stop) | $11.86 | $23.72 | 0.2372x |
| median structural stop 3.140% (NOT universal) | $7.60 | $15.20 | 0.1520x |
| structural 3.140% + hypothetical 2pp gap | $4.73 | $9.45 | 0.0945x |

At 25x instrument leverage, median-structural case at 0.5% stop-risk has nominal $15.20 and initial margin ~$0.61 on $100 equity, before other margin requirements. This illustrates why instrument leverage and account exposure are not interchangeable.

## Newly surfaced execution-policy ambiguity
The asymmetric-risk report says: "1% below/above entry, unless an existing structural stop is closer". D250 reports *median* structural stop 3.140%, but gives no per-trade distribution of which stop is closer. Therefore the exact per-trade operative stop is **not recoverable** from aggregate reports. No 67-row stop distances, Mark liquidation trajectories, or actual fill records are supplied by these reports. One cannot assert the median-structural scenario represents all trades.

The D250 source describes 67/67 positive gross movement to *future exact opposite extreme* (oracle), but only 67.16% causal opposite-confirmation wins (45/67 approximately); 61.2% median MFE giveback. The oracle-positive figure is **not** a realized win rate. The asymmetric 49.25% closed positive figure (33/67 approximately) is another exit/fee policy and must not be silently substituted.

## Executable reproduction (Python 3 standard library)
```python
equity=100.0
fee_pp=0.15
for d in (1.0, 1.958, 3.14, 5.14):
    print(d, round(equity*0.25/(d+fee_pp),2),
             round(equity*0.50/(d+fee_pp),2))
# 1.0 21.74 43.48
# 1.958 11.86 23.72
# 3.14 7.60 15.20
# 5.14 4.73 9.45
```

## Evidence status and next concrete replay gate
New matched historical executions: **0 verified**. Monthly net equity, MTM DD, actual stops/fills, mark-liquidation precedence, funding and MFE captured: **NOT COMPUTED**. The actual per-trade adverse excursion *before* D250 confirmation and LOW/HIGH split remain unavailable in these aggregate reports.

Recover the 67-row UTC manifest plus event-level bid/ask/mark/L50 and funding from Actions/external artifact stores, record evidence provenance and gaps, then pair unchanged 3x/5x baseline against 0.25/0.5% risk-budget variants with identical entry timestamps and causal exits. Enforce 1% portfolio aggregate reserved stop risk, avoid capital reuse and preserve previously rejected profit overlays as rejected. No unseen-forward claim without new independent observations.
