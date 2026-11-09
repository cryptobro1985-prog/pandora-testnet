# Next step — corrected full-micro cache

Status as of 2026-11-09:
- corrected rebuild launched by commit fa89f176e155a1887a386b5df6d9239bc1758813
- workflow run: 42619539996
- workflow: .github/workflows/hype-full-micro-202607.yml
- concurrency cancellation disabled
- automatic rebuilds from ordinary research-code pushes disabled
- clean cache is uploaded BEFORE model training
- artifact name prefix: HYPE-FULL-MICRO-CLEAN-CACHE-202607-
- retention: 90 days

## Hard gate
Do NOT use old Jul-Aug L50/liquidation snapshots for a new promoted rule.

The new cache must contain CLEAN_MICRO_AUDIT.json and pass:
1. valid L50 rows exist;
2. every row with fullmicro_book_valid=1 has positive spread;
3. crossed/locked books are masked, never model-valid;
4. liquidation validity exists separately for 5/15/60/180/300s;
5. invalid liquidation windows do NOT contain liquidation count/notional values masquerading as true zero.

If the clean audit fails, stop microstructure promotion and record the blocker.

## Once clean cache passes
Reuse the existing strict L6/K2 first-signal scorer and M1 candidate layer.
Do NOT restart broad feature search.

Run only these first three microstructure trajectory families, LOW/HIGH separately:

A. LIQUIDATION EXHAUSTION
- same-side liquidation burst before/near the candidate;
- decay from 30/60 -> 180/300s;
- normalized decay / half-life;
- require explicit stream-valid masks.

B. BOOK TRANSFER
- L10/L50 imbalance transition;
- bid/ask replenishment;
- cancellation/disappearance;
- absorption proxy;
- delta/trajectory rather than absolute snapshot.

C. IMPACT-EFFICIENCY TRANSFER
- old-side aggressive flow vs actual price displacement;
- new-side aggressive flow vs actual price displacement;
- ratio and slope at 30/60/180/300s;
- detect "aggression continues but price stops moving" on the old side.

Then test a staged conjunction:
STRUCTURAL EXTREME -> PRICE RESPONSE -> IMPACT EFFICIENCY TRANSFER -> LIQUIDATION EXHAUSTION -> BOOK TRANSFER.

Budget rules:
- sanity slice first;
- one Jul-Aug development block;
- kill any family that does not materially improve first-signal precision at useful recall;
- no chronological/sealed scoring until a frozen survivor exists;
- no broad hyperparameter sweep;
- maximum three active families per side;
- update WORK_PROGRESS.json and EXPERIMENT_LEDGER.jsonl before stopping.

Target:
improve terminal L6/K2 first-signal discrimination in the 30-70 bps zone.
Do not optimize internal L3/K1 and do not use the old May 31/31 as a strict-terminal comparator.
