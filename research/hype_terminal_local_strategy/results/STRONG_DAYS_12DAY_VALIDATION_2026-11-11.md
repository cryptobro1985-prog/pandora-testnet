# HYPE terminal-local strategy — 12 strong-day validation

Date: 2026-11-11

## Data used
12 completed strong-day overlays:
SEP03, SEP10, SEP17, SEP18, SEP30, OCT05, OCT08, OCT12, OCT22, OCT26, OCT27, OCT30.
Joined against the existing historical master compact M1 / strict H1 labels.

Strict terminal H1 labels inside the exact UTC days: 26 across 10 of the 12 days.
SEP17 and SEP18 contain useful market/regime negatives but no strict terminal label inside the exact UTC-day boundary.

## Rich-layer quality
- OI / mark / index / funding: present across all 12 overlays.
- Public long/short holder ratio: no historical rows returned on these old dates; must remain masked, never zero-filled.
- Liquidations: partial historical coverage depending on day (~70%–100% for 60s-valid minutes).
- L50: strong coverage on most October days and SEP17/SEP30; historical replay is sparse on SEP03/SEP10/SEP18 and must remain masked there.
- The derived basis field written by the fast collector is not trusted for this analysis; basis was recomputed from raw mark/index fields.

## Candidate contract used in this validation
- causal trailing 6h same-side extreme candidate;
- stronger same-side extreme invalidates/resets candidate;
- LOW and HIGH side-normalized;
- strict H1 labels are teacher/evaluation only, never model inputs;
- candidate snapshots tested after 30m, 60m, 120m of survival.

## Day-held-out validation
Each day was predicted by a model trained without that day.

Best broad terminal detector:
- 120m + core price/flow/structure + OI context
- TP=16, FP=6
- precision=72.7%
- recall=69.6%

High-precision earlier detector:
- 60m + core price/flow/structure
- TP=8, FP=3
- precision=72.7%
- recall=33.3%

Book and liquidation layers help conditionally, but because historical availability is uneven they did not produce a universal fixed rule by themselves.

## Strongest repeated terminal signature
The transferable pattern remains:

STRUCTURAL EXTREME
→ candidate survives without same-side extension
→ meaningful opposite price response
→ 3m/5m flow turns toward reversal
→ 3m/5m price-impact efficiency becomes positive for the new side
→ old-side efficiency decays
→ OI/positioning context does not contradict transfer of control
→ when valid, L50 replenishment/imbalance confirms book transfer
→ when valid, liquidation burst exhausts rather than continues.

Absolute reversal percent is descriptive, not the primary universal decision variable.

## Rejected “perfect” fixed rule
On these 12 days, this gate looked perfect:
- survive 60m;
- reversal >= 100 bps;
- side-normalized 5m flow >= 0;
- side-normalized 5m price-impact efficiency >= 0;
- <=15 same-side candidate rewrites in prior 6h.

12-day result: 7 signals, 7 TP, 0 FP (29.2% recall).

It was then checked on Jul12-Aug07 historical data.
Result: 11 signals, 7 TP, 4 FP = 63.6% precision.

Therefore this fixed gate is explicitly REJECTED as universal. It is a regime-specific high-confidence pattern, not a rule that “always works”.

## Final design direction
Do not use a single absolute % threshold.
Use a regime-normalized terminal score built from:
1. candidate survival / same-side reset;
2. reversal price response relative to recent candidate attempts;
3. side-normalized 3m/5m flow;
4. flow-to-price efficiency vs prior attempts;
5. OI delta / positioning lifecycle;
6. optional L50 confirmation only when book_valid=1;
7. optional liquidation-exhaustion confirmation only when liq mask is valid.

Entry tiers:
- EARLY: only when the regime-normalized score is extreme and all available rich layers agree;
- CONFIRMED: after stronger survival/response evidence;
- HARD: highest-confidence terminal state before holding toward the next opposite terminal local.

Missing rich streams are masks, never zeros.

## Conclusion
The 12 strong days materially improve the evidence, but they do NOT justify a claim of 100% universal local detection.
The next iteration should optimize a relative/regime-normalized score and validate it across Jul-Aug + Sep-Oct jointly, rather than hard-coding thresholds from one regime.
