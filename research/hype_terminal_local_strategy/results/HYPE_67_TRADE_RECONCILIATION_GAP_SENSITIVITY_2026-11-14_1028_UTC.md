# HYPE 67-trade evidence reconciliation and stop-risk sensitivity — 2026-11-14 10:28 UTC

Research only. No orders, no production changes, no detector retraining. Frozen D250 untouched.

## New cross-check on branch source documents
Read `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `trade_manifest_gate_research.py`, and `portfolio_stop_risk_guard_20261114.py` directly from the existing branch.

**Important correction:** the asymmetric 1%-cut audit reports 49.25% *positive after-cost* closed trades among 67, which rounds to 33/67. It reports 22 *fixed-cut exits*, not 22 losing trades and not 45 winners. Therefore `67 - 22 = 45` denotes non-fixed-cut exits, not 45 winners. The separate D250 causal opposite-local-only audit has 67.16% winners (~45/67) with a DIFFERENT exit rule. Do not merge these win rates, infer a per-trade mapping, or claim 45 winners in the cut audit.

The source itself gives a 5x $100->$1308.86 and closed DD 29.36%; 3x $100->$531.16 and closed DD 18.56%. Neither is verified tick-executable or mark-to-market. Its monthly balances cannot be treated as chronological calendar-month net equity without immutable trade timestamps and same-sample execution replay.

## New conservative sizing sensitivity (arithmetic, NOT Bybit replay)
Budget per trade $0.50 for $100 equity, 1% nominal price stop, 0.15% round-trip fees/costs, *additional* adverse stop-fill gap g. Notional = min($0.50/(0.0115+g), equity x allowed exposure cap). This is a stress sizing rule, NOT a maximum-loss guarantee.

| Extra adverse fill gap | Cost incl stop & fees | Max notional for $0.50 risk | Exposure |
|---|---:|---:|---:|
| 0% | 1.15% | $43.4783 | 0.4348x |
| 0.5% | 1.65% | $30.3030 | 0.3030x |
| 1.0% | 2.15% | $23.2558 | 0.2326x |
| 2.5% | 3.65% | $13.6986 | 0.1370x |
| 5.0% | 6.15% | $8.1301 | 0.0813x |

At 0.25% risk, halve the notionals. At portfolio stop-risk $0.80 already committed on $100, a new 0.5%-risk trade is capped at $0.20 available portfolio risk, not $0.50. An actual gap greater than g exceeds the assumed budget.

### Consequence for feasibility
A nominal 25x instrument leverage does not imply 25x account exposure: with $23.2558 notional and $100 equity, position margin at 25x is ~$0.93, but actual loss budget remains $0.50 in this scenario. Margin availability, Bybit minimum quantity/notional, tick/lot rounding, maintenance margin, mark-price liquidation, funding, fees, and actual executable spread must be checked **before** accepting a trade. If rounding to venue minimum would breach the risk budget, SKIP the trade. The stop must be on the safe side of liquidation under the exchange's actual risk-tier/margin mode, not a hypothetical fixed threshold.

## Why a replay is still blocked
The fetched `trade_manifest_gate_research.py` only checks strings for source names, not that source files or event spans exist. No 67-row immutable manifest with timestamped market-event evidence was verified in this iteration. Public trades cannot prove private fills. Therefore matched tick replay, monthly net equity, mark-to-market DD, MFE capture, fill count, and liquidation count remain **NOT VERIFIED**, not zero. The above arithmetic does not substitute for those metrics.

## Frozen protocol for next evidence-backed replay
1. Recover 67 chronological entry/exit IDs and actual signal-availability timestamps; independently hash and verify each source artifact.
2. Match each window to Bybit trades, L50, mark, liquidation, OI and funding *only where actually present*; explicitly report unavailable coverage.
3. Replay unchanged original baseline and risk 0.25%/0.5% with the same exact sample, costs and capital ledger. No capital overlap.
4. LOW->LONG and HIGH->SHORT separately; event-time stop and liquidation checks, conservative same-ms uncertainty, bid/ask modeled fills labeled as modeled.
5. Report monthly closed and mark-to-market DD, net equity, stops, fill quality, MFE captured/given back, and independent unseen-forward. Do not promote previously rejected MFE overlays without new forward evidence.

**Status:** evidence reconciliation and quantitative gap sensitivity complete; historical trade-event replay not complete.