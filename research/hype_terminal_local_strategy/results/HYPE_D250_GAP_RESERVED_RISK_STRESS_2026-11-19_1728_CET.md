# HYPE D250 — gap-reserved risk sizing stress, 2026-11-19 17:28 CET

Research-only checkpoint. No detector changes, live orders, production changes, or claim of historical Bybit fills.

## Provenance
Read frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, and quote_event_stop_replay_research.py directly from this branch. The 67-trade baseline is unchanged. The existing quote replay assumes a top-of-book hypothetical fill and does not verify liquidation, depth, or historical event matching.

## Executed deterministic stress
Ran `python risk_gap_test.py` locally (same content committed as `gap_reserved_risk_stress_20261119.py`); two invariant checks passed. Parameters: equity $100, stop adverse price 1%, round-trip fee allowance 0.15% of entry notional, risk 0.25% or 0.5%, reserved adverse execution gap 0/0.5/2 percentage points. No funding, borrow, book sweep, or liquidation model. This is an *arithmetic stress*, not a backtest. Risk-sizing formula: notional = min(equity*risk/(stop+fee+reserved_gap), equity*exposure_cap). Realized loss fraction = (notional/equity)*(stop+actual_gap+fee). Here exposure_cap=1x.

| Risk budget | Reserved gap | Notional $ | Loss if actual gap 0% | actual gap 0.5% | actual gap 2% |
|---|---:|---:|---:|---:|---:|
| 0.25% | 0% | 21.7391 | 0.2500% | 0.3587% | 0.6848% |
| 0.25% | 0.5% | 15.1515 | 0.1742% | 0.2500% | 0.4773% |
| 0.25% | 2% | 7.9365 | 0.0913% | 0.1310% | 0.2500% |
| 0.5% | 0% | 43.4783 | 0.5000% | 0.7174% | 1.3696% |
| 0.5% | 0.5% | 30.3030 | 0.3485% | 0.5000% | 0.9545% |
| 0.5% | 2% | 15.8730 | 0.1825% | 0.2619% | 0.5000% |

## Finding and boundary
Sizing for a 1% adverse price stop without gap allowance is NOT a hard 0.5%-equity loss cap: a 2-point gap generates 1.3696% equity loss. Reserving 2 points in the denominator reduces this synthetic loss to 0.5%, but **cannot guarantee** a maximum loss if the realized gap exceeds the reserve. This test does not establish which gap reserve is appropriate for HYPE; estimate it only from independently time-aligned historical quote/book events and validate out of sample. Stop trigger provenance, mark-price liquidation precedence, marketable fill depth and fees on actual executed notional remain unresolved. A portfolio risk budget of 1% must aggregate all open stop risks plus gap stress, and available margin must not be double-allocated.

## Next research gate
Locate UTC entry/exit ledger for all 67 D250 trades, and identify matching timestamped Bybit public trades, L50, mark and funding artifacts. Partition matched / partially matched / missing, with file paths, hashes, coverage and event ordering. Run unchanged baseline and conservative risk variants on identical matched trades only, report monthly MTM and closed DD, fills, stop counts, MFE and liquidation precedence; keep missing intervals UNRESOLVED rather than profitable. LOW/LONG and HIGH/SHORT separate. Do not promote previously rejected MFE overlays without independent unseen evidence.
