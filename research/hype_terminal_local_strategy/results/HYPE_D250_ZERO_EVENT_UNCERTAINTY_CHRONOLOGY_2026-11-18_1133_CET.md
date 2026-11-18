# HYPE D250 — executable-evidence boundary and zero-event uncertainty (2026-11-18 11:33 CET)

Research-only; no live orders, no detector retraining, no modification of frozen D250. This checkpoint uses the existing frozen reports and does NOT claim matched exchange replay.

## New quantitative finding: zero observed events is not a liquidation guarantee
For n independent Bernoulli trials with zero observed events, exact one-sided 95% upper event probability is 1 - 0.05^(1/n). For 67 hypothetical *independently and fully observed* trades, upper bound = 4.3728%. For 50 independent unseen confirmations with zero false-first, upper bound = 5.8155%. These are conditional statistical calculations, **not** empirical liquidation estimates: the historical 67-trade aggregate lacks validated mark-to-market paths, liquidation-tier calculations, real stop fills, and matched exchange execution events. Consequently n=67 is NOT an observed zero-liquidation sample. Also dependence/regime clustering invalidates the iid interpretation; these numbers are optimistic uncertainty illustrations only.

## Chronology audit of existing reported validation
The frozen D250 report labels May 2026 as sealed OOS but selects thresholds on Jul12–Aug07 and validates Aug08–Sep01. May predates development chronologically. It may be a valid withheld historical holdout but cannot be called a prospective chronological forward test. Sep01–Oct01 and Oct04–Nov03 are later in time; their integrity still depends on strict no-peek and unchanged frozen thresholds. None constitutes post-freeze November prospective evidence.

## Execution-level accounting blocker
The 67-trade 1% stop report provides counts, win rate, compound equity and closed DD but no per-trade UTC entries/fills/exits. Without per-trade data, reconstructing the same-sample, same-fee, funding-aware path is mathematically underdetermined. No monthly net MTM equity, realized fill rate, true liquidation count or MFE retention can be deduced from aggregates.

## Entry-to-execution contract (no fabricated observations)
- LOW->LONG: wait for frozen D250 eligibility and absence of intervening lower low or already confirmed opposite local. Marketable buy consumes ask; adverse stop market sell consumes bid.
- HIGH->SHORT: symmetric eligibility with absence of higher high; sell consumes bid; adverse stop market buy consumes ask.
- Both: timestamp every eligibility decision, reject gaps/stale L50 and missing feature provenance, use mark/last trigger basis as recorded, fees on actual fills, funding at actual settlement times, and Bybit tiered maintenance margin for liquidation checks.
- Portfolio: reserve 0.25–0.50% equity *modeled* stop risk per trade, at most 1% concurrent reserved stop risk, and never reuse unfilled exit capital. Scenario risk is not a maximum realized loss if gaps exceed the buffer.
- MFE: baseline 1% stop and causal opposite-K2 exit remains unchanged; previously rejected overlays stay rejected. New control-transfer exit is only a research challenger, requiring independent future evaluation, not retrofitted claims.

## Reproducible arithmetic
```python
from math import pow
for n in (67,50):
    print(n, 100*(1-pow(0.05,1/n)))
```

## Status and next required empirical step
Read existing UTC-level trade ledger and exchange event archives if present in GitHub/Actions artifact storage; verify hashes and continuity; replay baseline and challengers on identical chronological trades and costs. This iteration inspected frozen reports, quantified the statistical evidence boundary and flagged the May chronology classification. It did not recover individual trades or execute exchange-event replay; do not promote a strategy from this checkpoint.
