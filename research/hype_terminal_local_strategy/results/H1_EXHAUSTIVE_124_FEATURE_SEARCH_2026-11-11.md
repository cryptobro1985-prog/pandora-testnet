# HYPE H1 exhaustive causal search — 124 slots
Date: 2026-11-11. Research only; no live trading code changed.

## Scope
- 12 selected strong days with the existing 12 strategic groups + 7 rich blocks.
- 124 available slots in the H1-close audit: 118 market features + 6 quality/validity masks.
- Quality masks used as data validity, not directional market signals.
- LOW and HIGH searched separately and jointly.
- No fixed retracement-percent trigger.
- Chronological split on the 12 days: first 6 discovery, next 3 validation, last 3 untouched test.

## Exhaustive 12-day search
Thousands of one- to four-condition conjunctions were searched across all available market slots.

Rules with 0 FP on discovery+validation are easy to produce, but most fail on untouched final days:
- LOW greedy zero-FP-on-first-9 ensemble: final 2 TP / 2 FP.
- HIGH greedy zero-FP-on-first-9 ensemble: final 0 TP / 1 FP.
- Joint greedy zero-FP-on-first-9 ensemble: final 3 TP / 4 FP.

A small number of individual LOW rules stayed 0 FP across all three chronological partitions, with best support 3 TP discovery + 1 TP validation + 2 TP final = 6/13 LOW terminals and 0 FP. No comparable HIGH rule caught final HIGH terminals at 0 FP.

Using all 12 days at once, it is possible to cover all 25 terminal locals with an OR of 8 zero-FP rules, but this is in-sample memorization and is explicitly rejected as evidence of a universal signature.

## Larger Jul-Nov causal check
Existing full-history H1 feature replays contain 1,089 H1-close candidate events across four chronological historical segments:
- segment 1 Jul12-Aug07
- segment 2 Aug08-Sep01
- segment 3 Sep01-Oct01
- segment 4 Oct04-Nov03
Total terminal labels: 258.

A nested relational search uses earlier segments to select relational patterns and the next segment to set consensus; segment 4 remains final test.

### Exact H1 close
Final segment: 1 TP / 1 FP. Therefore exact-close zero-FP universal detection is NOT demonstrated.

### Delay sweep after completed H1
Nested causal relational consensus final-segment results:
- 0m: 1 TP / 1 FP
- 5m: 0 / 0
- 10m: 0 / 0
- 15m: 0 / 0
- 20m: 0 / 0
- 25m: 6 / 1
- 30m: **5 / 0**
- 35m: 1 / 1
- 40m: 2 / 1
- 45m: 0 / 0
- 50m: 0 / 0
- 60m: 2 / 0
- 90m: 0 / 0
- 120m: 2 / 0

The 30-minute consensus is the strongest tested zero-FP transferable point.

Across all four historical segments, the frozen 30m consensus produced:
- Jul12-Aug07: 3 TP / 0 FP
- Aug08-Sep01: 4 TP / 0 FP
- Sep01-Oct01: 6 TP / 0 FP
- Oct04-Nov03 final: 5 TP / 0 FP
Total = **18 TP / 0 FP** on 258 terminal labels, ~7% terminal coverage.

## Nature of the stable 30m relationship
The consensus does NOT rely on a price retracement percentage. It repeatedly uses pre-existing relationships among:
1. H1 structural step / reversal geometry;
2. short-vs-long aggressor-flow imbalance;
3. new-side executed-notional dominance;
4. new-side price-impact efficiency;
5. old-side loss of price impact / absorption;
6. relative 1/3/5/15/30/60-minute behavior.

Signal requires agreement of at least 3 independently mined relational patterns (q=3 in the nested search). Individual raw thresholds are not proposed as live trading rules.

Rich-layer caveat: historical L50 dynamics, holder ratio and some liquidation data are not uniformly present over Jul-Nov, so they cannot be claimed as universal required components. On the 12 rich days, rich data improved some separations but did not create a transferable zero-FP HIGH detector.

## Verdict
A zero-false-positive subset exists, but at current evidence it catches only a small fraction of terminal H1 locals. Perfect or near-complete zero-FP detection at the exact H1 close has NOT been found. Any 25/25 zero-FP construction on the same 12 days is overfit and must not be promoted to live trading.
