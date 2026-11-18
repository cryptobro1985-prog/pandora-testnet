# D250 execution replay — May cohort coverage gate (2026-11-18 15:33 CET)

Research only. Frozen entry, 1% adverse stop, rejected overlays and production untouched. No orders.

## New cross-source cohort reconciliation

Read original frozen D250 walk-forward report, original 67-trade asymmetric-risk report, recovered Actions artifact audit, rich-source recovery audit and direct source inventory from this branch.

**Critical coverage mismatch:** The frozen D250 accepted signals are distributed across **five** disjoint historical evaluation windows: May 2026 (15), Jul12–Aug07 (9), Aug08–Sep01 (12), Sep01–Oct01 (23), Oct04–Nov03 (12). Sum = 71. The recovered Actions artifact 13650399622 has compact M1 streams for only **four** windows (Jul12–Nov03), 157,375 rows, with **no May 2026 stream**. Thus even a perfect reconstruction of this artifact cannot independently replay the *full* five-window 67-completed-trade baseline. The 67-trade report publishes May cumulative equity ($100->$471.51 at 5x) but no May UTC ledger. The May 15 accepted signals cannot be mapped to completed trades by count.

**Actionable implication:** A four-window replay must be labeled **partial, May-excluded** and MUST NOT be compared to published five-window terminal $1,308.86 / 29.36% closed DD or 3x $531.16 / 18.56% DD as if samples match. The missing May period is a hard cohort gate, not a zero-return month. Likewise a May historical holdout is not future forward relative to July development.

## Exact cohort reconciliation assertions for replay

1. Obtain 71 immutable signal IDs and availability timestamps, including 15 May, then establish the mapping to 67 completed and 4 censored episodes from source code or ledger; no count-based joining.
2. For each of the five windows report `accepted_signals`, `completed`, `censored`, `M1_coverage`, `mark_coverage`, `L50_coverage`, `trade_tape_coverage`, `funding_coverage`. Use UNKNOWN rather than zero for missing execution evidence.
3. Reproduce original 67-trade model on the **same five-window cohort** before comparing sizing/stop variants. A four-window exploratory OHLC bound is separate and cannot inherit published aggregate performance.
4. Use chronological calendar ordering for MTM and equity DD; no interpolation of the May-to-July gap or fabricated flat returns. For stop ambiguity use conservative stop-first OHLC bounds, but do not present these as actual fills.
5. No promotion of MFE exit overlay absent independent unseen-forward validation; opposite K2 confirmation remains the frozen causal comparator.

## Reproducible source-check pseudocode

```python
signals = {'May':15,'Jul':9,'Aug':12,'Sep':23,'OctNov':12}
artifact_periods = {'Jul','Aug','Sep','OctNov'}
assert sum(signals.values()) == 71
assert set(signals) - artifact_periods == {'May'}
assert sum(signals[k] for k in artifact_periods) == 56
# 56 signals is NOT 56 completed trades, and 15 May signals are NOT 15 May fills.
# Full 67-trade performance comparison must FAIL until May and immutable IDs recovered.
```

## Result and limits

New concrete cross-source cohort/coverage gate: **15/71 frozen accepted signals (21.13%) are in May, absent from the recovered four-period M1 artifact; 56/71 (78.87%) are in its date windows**, but this does not establish signal-level bar coverage. No raw tick tape, May M1 stream or immutable 67-row ledger recovered in this iteration. No matched execution replay or new verified PnL, fills, MTM DD, liquidations or MFE preservation. Next priority: find May artifact and immutable per-signal timestamps, then run identical cohort replay. Do not refit frozen D250.
