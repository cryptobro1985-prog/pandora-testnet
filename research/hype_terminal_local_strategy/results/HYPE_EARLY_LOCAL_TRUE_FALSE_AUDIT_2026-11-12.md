# HYPE Early Local TRUE/FALSE Audit — 2026-11-12

Research only. Real orders OFF.

## Objective
Classify each causal 6h-extreme Local candidate as TRUE / FALSE as early as possible, with the decision no later than ~0.40% reversal from the candidate extreme. Strict H1 labels are teacher/evaluation only and are never predictive inputs.

## Data
Preserved causal M1 history:
- sealed May 2026
- Jul12-Aug07
- Aug08-Sep01
- Sep01-Oct01
- Oct04-Nov03

Fresh replay built from compact M1:
- 8,665 raw Local candidates
- 11,324 causal snapshots at first 0.25 / 0.30 / 0.35 / 0.40% reversal
- 323 unique strict TRUE candidates in the replayable set
- 2,518 candidates reached the 0.40% reversal checkpoint before same-side invalidation/end
- all 323 TRUE candidates reached 0.40% in this preserved sample

Period counts at 0.40%:
- May: 557 candidates / 65 TRUE
- Jul: 343 / 45 TRUE
- Aug: 470 / 64 TRUE
- Sep: 658 / 73 TRUE
- Oct: 490 / 76 TRUE

## Anti-leakage protocol
- candidate = new 6h running extreme
- more-extreme same-side candidate invalidates old lineage immediately
- features are computed only from data available at the signal timestamp
- teacher TRUE/FALSE is assigned only after feature generation
- model development: Jul + Aug
- threshold calibration: September
- untouched checks: October + sealed May

## Result 1 — survival to 0.40% is useful but not sufficient
Only 2,518 / 8,665 raw candidates reached 0.40% reversal while all 323 TRUE candidates did.
This is a strong structural rejection layer, but precision at 0.40% remains only ~12.8%, so it cannot itself authorize full-size entry.

## Result 2 — common M1 price/flow/MFI binary TRUE classifier failed transfer
47 causal features were tested, including:
- reversal speed and reversal/range60
- pre-move size
- ATR-normalized state
- 1/3/5/10/15/30/60m side-normalized returns
- aggressor flow
- flow/price efficiency
- trade and turnover activity ratios
- persistence
- MFI14 side state and delta

ExtraTrees + RandomForest + Logistic ensemble:
- trained only Jul + Aug
- threshold selected only on September
- no high-precision TRUE region transferred to both October and sealed May with useful coverage

Example: the only September 100%-precision TRUE cell found in the tested grid (HIGH at 0.35%) produced 0/1 on October and 1/3 on May. Therefore it is rejected.

Conclusion: do NOT use a fixed early TRUE classifier from price/flow/MFI alone.

## Result 3 — selective FALSE classification transfers better
A high-confidence FALSE branch is materially more stable than TRUE.

Example conservative HIGH 0.40% branch:
- ensemble P(TRUE) <= 0.055
- September: 47 FALSE correctly rejected / 0 TRUE wrongly rejected
- October untouched: 7 / 0
- sealed May untouched: 6 / 0
This branch is precise but low coverage and therefore is only a hard-reject layer, not a complete classifier.

Broader FALSE thresholds increase coverage but begin rejecting some real Locals, so they are not promoted as hard rules.

## Result 4 — old early fixed rules remain rejected
EARLY60 strong reversal had already failed untouched September:
- HARD120 alone precision 86.15%
- HARD120 + EARLY60 stack precision 82.35%
- HIGH stack precision 77.78%
Therefore it remains diagnostic/shadow only.

## Rich microstructure evidence
The strongest observed causal mechanism remains:
STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY / CONTROL TRANSFER

Observed true-vs-false signatures:
LOW:
- faster positive reversal response
- buyer flow moves price efficiently
- long-liquidation burst exhausts
- L10/L50 bid-side recovery

HIGH:
- persistent negative reversal response
- seller flow moves price efficiently
- short-liquidation squeeze exhausts
- near-book shifts toward ask pressure

However identical full L50/OI/liquidation history is not preserved across every month. Therefore a universal early TRUE gate using rich features cannot yet be honestly certified across all periods. Missing rich fields must never be zero-imputed.

## Promoted stable architecture
The early classifier is now selective, not forced-binary:

1. FALSE_STRUCTURAL
   - same-side more-extreme print invalidates the prior candidate immediately.
   - no trade from the invalidated candidate.

2. FALSE_HIGH_CONFIDENCE
   - ensemble FALSE probability region calibrated chronologically.
   - only thresholds that preserve no/near-no TRUE rejection on untouched periods are eligible.
   - current strongest fully clean example: HIGH at 0.40%, P(TRUE)<=0.055.

3. TRUE_RICH
   - full-size activation is allowed only when the complete causal transfer chain is present:
     a) candidate survives,
     b) reversal response is persistent,
     c) new-side flow is price-efficient,
     d) old-side liquidation pressure is exhausting,
     e) L50/book state recovers/transfers,
     f) OI/positioning does not contradict the transfer.
   - this branch remains SHADOW until enough rich months exist for untouched cross-regime certification.

4. UNCERTAIN
   - everything else.
   - must not be mislabeled TRUE.
   - may later be used for a tiny probe/bounce system, but not full-size Local swing activation.

## Why this is the stable result
Forcing every 0.25-0.40% candidate into TRUE/FALSE produced regime failure.
Allowing UNCERTAIN prevents false certainty and preserves causal correctness.
The production objective should therefore be:
- aggressively reject proven false lineages,
- authorize full-size trades only in high-confidence TRUE states,
- keep uncertain candidates out of the full-size swing engine,
- continue collecting rich L50/OI/liquidation evidence to increase TRUE coverage without sacrificing transfer.

## Next research target
Increase TRUE_RICH coverage under a frozen chronological protocol:
- discovery: Jul/Aug rich
- validation: later rich days
- untouched final score: latest unseen rich days
Promotion requires zero/near-zero false-first signals and no threshold changes after freeze.
