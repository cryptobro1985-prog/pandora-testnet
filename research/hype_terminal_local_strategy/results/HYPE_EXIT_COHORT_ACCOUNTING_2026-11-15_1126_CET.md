# HYPE frozen-entry trade-cohort accounting — 2026-11-15 11:26 CET

Research only. Existing branch. No orders, no detector training, no threshold changes.

## Evidence inspected
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md
- HYPE_RECOVERED_ARTIFACT_M1_CONTINUITY_2026-11-15_1026_CET.md

## New cohort decomposition from frozen aggregate results

Original fixed 1% adverse-price cut, no tight trail, 67 completed sequential simulated trades, 22 fixed-cut exits, 49.25% positive closed trades after modeled costs.

49.25% * 67 rounds to **33 positive closed trades**, leaving **34 non-positive trades**. If all 22 fixed-cut exits were net losses (as expected under a 1% adverse cut and positive costs, but must be verified against the trade ledger), then:
- 22 stop exits = 32.84% of completed trades;
- 45 non-stop exits = 67.16% of completed trades;
- 33 of 45 non-stop exits net positive = 73.33%;
- 12 of 45 non-stop exits net non-positive = 26.67%;
- 12 of 34 non-positive exits = 35.29% of losses were **not** fixed-cut exits.

The 12 count is **conditional on stop exits all being net losses**, not a direct replay observation. It is a concrete testable ledger reconciliation invariant, not a claim that the 12 exits were necessarily opposite-local exits; other exit reasons must be read from the trade ledger.

### Why this matters
Protecting MFE is not reducible to improving stop handling. Even after a frozen 1% cut, potentially 12 losing episodes survived the stop and finished non-positive. They require **separate** event-level examination of adverse excursion, peak MFE, causal opposite-local confirmation, and post-entry sustained opposite price-impact/control transfer. The earlier rejected MFE/flow and K0/K1 overlays remain rejected; no thresholds are proposed here.

## Replay join contract (actionable next step)
For each of the 71 accepted first signals, record: unique episode ID; LOW/HIGH; original extreme time; D250 *availability* time; entry request and earliest executable time; source M1 interval; open/high/low/close; known exchange/receipt time; entry bid/ask or unknown; fixed stop trigger and possible fill range; first stop-versus-exit ordering; exit reason; MFE/MAE path bounds; trade cost, funding, equity and overlap state.

Four unfinished/censored episodes must **not** be silently dropped or assigned zero PnL. Compare all 67 completed trades and the four censored records with the frozen ledger, not 71 assumed closes.

When M1 high/low spans both stop and exit thresholds and the event order is unavailable, report both admissible outcomes; do not choose the favorable order. Five timestamp gaps across the recovered 157,375-row M1 artifact require unknown-execution labels where the gap intersects a trade. Bid/ask, mark liquidation, L50 queue and tick fills are NOT supplied by the recovered M1 tape.

## Reproducible arithmetic
```python
n=67
positive=round(n*0.4925)
stops=22
nonpositive=n-positive
survivors=n-stops
assert positive==33 and nonpositive==34 and survivors==45
print(dict(positive=positive,nonpositive=nonpositive,stops=stops,
           non_stop_positive_if_stops_loss=positive,
           non_stop_nonpositive_if_stops_loss=nonpositive-stops,
           non_stop_win_fraction_if_stops_loss=positive/survivors))
```

## Evidence boundary
This iteration provides a **new, auditable cohort-accounting diagnostic**, not a new per-trade market replay or forward performance claim. No newly verified fills, monthly net equity, MTM DD, liquidation count, or MFE capture. Frozen D250, 1% stop, same-sample baseline and previously rejected protection overlays unchanged. No production changes or real orders.
