# HYPE Every-Local Robust Strategy — 2026-11-12

Research/paper only. Causal features only; strict labels are evaluation-only.

## Coverage
- 7,753 causal 6h-extreme Local candidates processed across sealed May + Jul12-Nov03 preserved history.
- 322 strict finalized H1 Locals in those periods.
- Multi-stage hierarchy produced a causal trading state for all 322/322 strict Locals.
- 717 candidate trade paths had a completed opposite-Local evaluation path.
- Single-position sequential execution produced 411 actual trades in the robust configuration; overlapping candidates were processed but did not reuse the same capital simultaneously.

## Candidate hierarchy
1. +60m: require >=45 bps reversal from candidate.
   - Tier A if rev_atr >= 0.40, prior 180m move <= 450 bps, and 15m trade activity ratio >= 0.50.
   - otherwise Tier B.
2. If no +60m signal, +120m fallback: >=25 bps reversal => Tier C.
3. If still no signal, +180m fallback: >=25 bps reversal => Tier D.
4. Same-side more-extreme print invalidates the old candidate lineage.

## Trading logic
### Tier A — full swing
- Hard stop: 5 bps beyond candidate extreme.
- Maximum account exposure: 5x.
- Round-trip cost assumption: 0.15% of notional.
- Profit protection on runner:
  - MFE >= +2% => floor +0.25% from entry (activates next minute)
  - MFE >= +4% => floor +1.5%
  - MFE >= +6% => floor +4%
- Otherwise hold runner until causal confirmation of the opposite strict H1 Local (K2 availability).

### Tier B/C/D — weak/false-Local bounce trade
- Tiny risk budget: 0.025% of equity.
- Hard stop remains behind candidate extreme.
- Take profit: +1.2% price move.
- Maximum lifetime: 120 minutes; otherwise close at market/close at timeout.
- Purpose: monetize short bounce / occupy weak state briefly without treating it as a full swing.

## Dynamic Tier-A risk governor
- Normal Tier-A risk budget: 7% of equity, but actual exposure is capped at 5x.
- If current equity drawdown >=15%: cut Tier-A risk to 3.5%.
- If drawdown >=20%: cut to 1%.
- If sum of last 5 Tier-A equity returns <= -1%: cap risk at 2.45%.
- If recent Tier-A return sum >= +3% and drawdown <7.5%: allow normal risk again.

## Selection / validation protocol
The configuration was selected without using October:
- development: Jul12-Aug07 + Aug08-Sep01
- validation: Sep01-Oct01
- sealed secondary validation: May 2026
- untouched final test: Oct04-Nov03

All candidate decisions use only data available at the decision timestamp. Future strict labels are evaluation-only.

## Sequential compound from $100
Using the single-position chronological replay:
- start: $100.00
- after May: $103.98
- after Jul12-Aug07: $144.38
- after Aug08-Sep01: $335.30
- after Sep01-Oct01: $422.36
- after Oct04-Nov03: $482.77

Final: $482.77
Maximum closed-equity drawdown: 29.12%
Executed trades: 411
Win rate: 43.55%
Profit factor on equity-return sums: 1.675
Average winning equity return: +3.21%
Average losing equity return: -1.48%
Maximum loss streak: 9
Worst modeled trade: about -7.0% equity
Best modeled trade: about +130.6% equity

## Standalone regime checks from $100
- May: $103.98, max DD 24.45%
- Jul: $177.26, max DD 19.61%
- Aug: $220.00, max DD 19.76%
- Sep: $143.75, max DD 29.12%
- Oct untouched final test: $138.99, max DD 25.37%

## Aggressive all-history frontier (NOT an honest OOS result)
A configuration selected after inspecting all preserved periods reached roughly $965.56 from $100 with ~29.19% DD. It is not promoted because May/October influenced parameter choice. It is only evidence of optimization headroom, not a deployable result.

## Verdict
The system now processes every causal Local candidate rather than only 67 high-confidence confirmations. All 322 strict Locals received a causal A/B/C/D trading state. The robust, non-October-tuned result is $100 -> $482.77 with 29.12% max DD. This is materially more complete but still far from a defensible "millions" claim. The remaining bottleneck is not Local coverage; it is improving the money-management/exit edge on Tier A and making B/C/D positive-expectancy without overfitting.
