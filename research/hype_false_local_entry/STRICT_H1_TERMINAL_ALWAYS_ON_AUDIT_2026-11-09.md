# HYPE Strict H1 Terminal Local — Deep Causal Audit — 2026-11-09

## Scope
Stored HYPE history: 2026-07-12 17:00 UTC through 2026-11-03 00:00 UTC, four blocks.
Reference contract: strict H1 L6/K2 with consecutive same-side pivots collapsed to the more extreme pivot.
Stored terminal label set: 264 = 132 LOW + 132 HIGH.

## Critical correction: K2 pivot != terminal Local
A raw H1 K2 pivot is not guaranteed to be the final Local. Consecutive pivots of the same side can occur; the later more-extreme pivot replaces the earlier one in the strict alternating label set.

Raw K2 pivots versus terminal/collapsed labels:
- Jul/Aug: 92 raw K2 pivots -> 48 stored terminal labels.
- Late-Aug: 97 -> 65.
- September: 123 -> 74.
- Oct/Nov: 114 -> 77.

Therefore a real-time system must distinguish:
1. PIVOT_PROVISIONAL: K2 confirmed, but can still be superseded by a stronger same-side K2 pivot.
2. PIVOT_REPLACED: a stronger same-side K2 pivot replaces the provisional one.
3. TERMINAL_FINAL: only when an opposite K2 pivot is confirmed does the previous pending pivot become final in the alternating strict-local sequence.

This state machine reproduces the collapse semantics causally. It never needs to claim that a provisional pivot is terminal-final.

## Terminal finalization delay
For reference-finalized stored locals:
- LOW: n=130. Median terminal-final delay from exact extreme = 10.62 h; p10=5.86 h; p90=20.68 h; max=58.54 h. Median price displacement at finalization = 2.13%; p90=5.68%; max=27.07%.
- HIGH: n=129. Median delay = 9.50 h; p10=5.10 h; p90=23.02 h; max=45.00 h. Median displacement = 2.16%; p90=5.11%; max=12.39%.

Thus terminal finality is deterministic but far too late for an optimal trading entry. Early entry is necessarily predictive/probabilistic.

## Strict H1 early-candidate plane
Candidate definition used for the final audit:
- current in-progress H1 breaks the extreme of the six fully completed preceding H1 hours;
- any more-extreme same-side move invalidates/replaces the old candidate immediately;
- all features are causal at the sampling timestamp.

There are 131 evaluable true candidates per side across the stored blocks (the remaining edge labels lack enough preserved prior context).

At +120 minutes, before additional indicator filters, precision of surviving strict-H1 candidates is still insufficient:
- Jul/Aug: LOW 23 true / 33 false; HIGH 23 / 24 false.
- Late-Aug: LOW 32 / 15 false; HIGH 33 / 29 false.
- September: LOW 37 / 27 false; HIGH 37 / 33 false.
- Oct/Nov: LOW 39 / 33 false; HIGH 38 / 15 false.

## Honest chronological transfer
Rules were selected ONLY on Jul/Aug. Late-Aug, September and Oct/Nov were used only for evaluation.

LOW +90m:
- rule: retrace_bps >= 157.4381 AND ret_180 >= 0.00305672
- Jul/Aug: 10/10
- later periods: 19 true / 1 false = 95.0%
- late-Aug 5/5, September 8/9, Oct/Nov 6/6

HIGH +90m:
- rule: pos_1440 <= 0.3000817
- Jul/Aug: 6/6
- later periods: 13 true / 1 false = 92.86%
- late-Aug 2/3, September 8/8, Oct/Nov 3/3

No honest early rule tested reached 100% cross-regime precision with useful support.

## Direct price-distance test
Snapshots were taken at the first causal M1 close reaching 30/40/50/60/70/80/100 bps retracement from a strict H1 candidate, with same-side invalidation.

Result:
- 30–50 bps (0.3–0.5%): no useful zero-false rule transferred chronologically.
- 60–70 bps (0.6–0.7%): small development-only LOW pockets exist, but honest transfer was not robust; HIGH transfer degraded badly.
- 100 bps: development-only HIGH combinations exist, but they are selected on the same four periods and are not OOS proof.

Therefore the requested guaranteed 0.4–0.7% terminal-local detector is not solved by the common historical feature plane.

## Development-fit zero-false shadow layer
Using all four stored periods for discovery (NOT untouched OOS):
- LOW: 78 / 131 evaluable terminal candidates covered with zero historical false candidates = 59.5% coverage.
- HIGH: 75 / 131 = 57.3%.
- Combined: 153 / 262 = 58.4% historical early coverage with zero historical false candidates.

Signal timing/distance:
- LOW: median age 90m; median distance from true LOW 1.709%; p90 2.791%.
- HIGH: median age 120m; median distance 1.500%; p90 2.761%.

These rules are SHADOW/PROBABLE only. They are not guarantees because the same history was used to select them.

## Robust operating system
State contract:
1. WATCH — in-progress H1 breaks previous six completed H1 extremes.
2. RESET — any stronger same-side extension replaces the candidate.
3. PROBABLE_SHADOW — causal full-116/indicator signatures may score probability, but never authorize TERMINAL_FINAL.
4. K2_PIVOT_PROVISIONAL — two-H1 K2 condition confirms a pivot, still revisable.
5. PIVOT_REPLACED — later stronger same-side K2 pivot replaces provisional pivot.
6. TERMINAL_FINAL_AND_FLIP — when an opposite K2 pivot confirms, the pending previous-side pivot becomes terminal-final and the opposite pivot becomes new provisional.

This is the only architecture that can "always work" without lying: it permits abstention and revision. It cannot guarantee future early prediction because terminality is a future-dependent property.

## 99.9% claim
264 historical terminal locals cannot establish 99.9% future precision, especially after feature/rule selection. With zero failures, roughly 3,000 independent forward successes are needed for a one-sided 95% binomial lower bound near 99.9%.

## Verdict
- Exact terminal-local tracking eventually: solved causally by provisional K2 pivots + same-side replacement + opposite-pivot finalization.
- Useful early LOW prediction: ~95% honest later-period precision for the selected +90m rule.
- Useful early HIGH prediction: ~92.9% for the selected +90m rule, but weaker regime stability.
- Guaranteed 0.4–0.7% early terminal detection: not supported by current evidence.
- Next valid step: freeze all development rules and score them on new full-116 forward data without retuning.
