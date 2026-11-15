# Frozen 1% stop: execution boundary audit — 2026-11-15 15:34 CET

Research only. No retraining, live orders, production changes, or promotion of rejected exit overlays.

## Sources checked in this iteration
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `strict_execution_provenance_research.py`

## Concrete new audit: the reported worst loss is exactly the frictionless stop-model loss
Frozen adverse-price cut = 1.00%; assumed round-trip notional cost = 0.15%.
For exposure E = notional/equity, a stop at exactly 1% with no gap produces loss/equity = E*(0.01+0.0015).

- 3x: 3*(0.0115) = 3.45% of equity, exactly equal to reported worst modeled trade -3.45%.
- 4x: 4*(0.0115) = 4.60%, exactly equal to reported worst modeled trade -4.60%.
- 5x: 5*(0.0115) = 5.75%, exactly equal to reported worst modeled trade -5.75%.

**Interpretation:** the reported worst modeled trade is *consistent with* exact-at-stop fills and flat cost, and provides **no observed adverse stop-gap allowance**. It does not establish that all 22 stop fills were exact, nor that liquidation was absent. An actual 0.5% extra adverse gap would yield -8.25% equity at 5x; a 1% gap -10.75%, before any incremental funding/cost. This is deterministic sensitivity, NOT market replay.

## Risk sizing, fixed and frozen entry/stop
For equity $100, total assumed cost 0.15% of notional, stop 1%, additional adverse fill gap g:
`max_notional = equity * risk_fraction / (0.01 + 0.0015 + g)`.
No claim that the gap cap is enforceable. For g=1%, 0.25% risk -> $11.6279 notional; 0.5% -> $23.2558. At g=0%, 0.25% -> $21.7391; 0.5% -> $43.4783. Maximum combined nominal stop-risk 1% of equity across concurrently open positions; reject if margin/liquidation buffer inadequate.

## Execution provenance gate limitations found in reviewed source
The strict gate hashes files and checks declared start/end timestamps, but it does not parse the evidence contents or independently verify the claimed timestamp range, ordering, price/size, actual bid/ask, order ACK or Bybit mark-price liquidation path. Its self-test reuses one four-byte text fixture for every evidence role, including L50, public trades, stop order and mark path. Consequently, the passing self-test verifies file hash handling only, not market provenance or execution validity. This is a new source-level finding, not a per-trade replay.

## Next non-optional matched-trade replay
1. Recover the 67 completed trades and four pending episodes with causal entry timestamps, sides and stop prices, and locate actual M1/Public Trades/L50/OI/liquidation evidence for each.
2. Keep original frozen baseline and candidate risk-sized variants on the *same* timestamped episodes. No same-minute stop/target ordering guesses; ambiguous OHLC bars receive worst-case bound or excluded coverage.
3. Separate LOW->LONG and HIGH->SHORT adverse excursion between candidate extreme and signal availability, and after entry; enforce first causally available opposite local.
4. Recompute fees, funding, spread, price gaps, liquidation thresholds, monthly closed and mark-to-market equity/DD, MFE capture/giveback, and genuinely unseen forward results.
5. Maintain rejected profit-protection overlays as rejected unless new independent chronological evidence demonstrates transfer.

## Status
**No event-level replay completed in this iteration.** No new net-equity, fills, MFE protection or liquidation count is claimed. Existing 71/71 classification does not imply 71 profitable executable trades. The frozen 1% cut is an exploratory candidate, not a guaranteed hard loss bound.
