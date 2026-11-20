# D250: frozen 67-trade baseline vs risk-limited account exposure — 2026-11-20 22:30 CET
Research only. No orders, no production change, no detector retraining.

## Source reconciliation (directly read from this branch)
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: 71 accepted first signals, 67 with finalized opposite local; 67 is not an independent fresh-forward set. Frozen D250 thresholds remain unchanged. Median MFE giveback on causal opposite-local exits 61.2%.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 sequential *modeled* trades, 22 adverse-price cuts, 0.15% round-trip notional cost assumption; 3x account exposure $100->$531.16, 18.56% closed DD; 5x exposure $100->$1308.86, 29.36% closed DD. Not real order fills, not MTM DD.
- 1% adverse-price cut is a price trigger, **not** a 1% equity risk bound. The historical baseline applies 3x/5x *account exposure*, not 0.25–0.5% stop-risk sizing.

## New quantitative compatibility audit
Assume the original 1.00% adverse-price stop, 0.15% round-trip fees, no funding, no gap/slippage; let exposure = notional/equity. Stop-loss equity fraction = exposure * (0.0100+0.0015).
- At 3x: 3.45% equity per stopped trade, before gap/funding; at 5x: 5.75%. Both exceed a 0.5% stop-risk mandate by factors 6.90 and 11.50.
- Max exposure for 0.50% stop-risk is 0.005/0.0115 = **0.4347826x** equity; for 0.25%, **0.2173913x** equity.
- With an illustrative extra 0.5% adverse execution gap/slippage, effective adverse cost = 1.65% notional: exposure caps **0.3030303x** (0.50% risk) and **0.1515152x** (0.25% risk).
- With an illustrative extra 2.0% adverse gap/slippage, effective adverse cost = 3.15%: caps **0.1587302x** and **0.0793651x**.
- At $100 equity and 0.5% stop-risk, 2% extra gap reserve: maximum hypothetical notional $15.873; this is **not** evidence that Bybit permits this minimum order.
- Portfolio stop-risk 1% requires sum of each concurrently open position's stress stop-risk <=1% equity; sequential 67-trade baseline alone cannot validate concurrent capital reuse.
- If entry is 250 minutes after local extreme, any movement before the causal entry is not trade MAE and cannot be counted as realized PnL.

## Falsifiable inference
The published 3x and 5x compound returns are **not transferable** to 0.25–0.5% equity-risk trading by changing a label. The sizing rule reduces exposure materially; profitability, fees, minimum lot, fill probability, MTM DD, and month-by-month net equity must be recomputed trade by trade. A 1% stop does not guarantee a 1% price loss when triggered through Mark Price and filled at executable bid/ask.

## Blocking evidence for a historical execution replay
For each of 67 records require UTC causal signal, original local side, first eligible quote, actual bid/ask and executable depth, instrument filters, Mark Price tape with integrity/gap metadata, adverse stop trigger timestamp, bid/ask/depth at exit, funding interval and rate, fee schedule, next opposite-local *availability* timestamp, and source IDs/hash. Reject unknown coverage; do not zero-impute missing streams. A verified absence of liquidation requires continuous mark/position-margin reconstruction.

## Next replay protocol (unchanged baseline vs alternatives)
Freeze the 67 original signal timestamps and baseline rule; assign all variants the same observable events and identical realistic costs. Separately report LOW->LONG and HIGH->SHORT, unmatched/missing events, missed fills, price-gap stops, position sizes, liquidation-distance buffer, equity MTM and closed DD, monthly net equity, MFE realized/given back, and unseen-forward periods. Baseline 3x must remain explicitly labeled non-risk-compliant; compare 0.25/0.5% stop-risk variants and staged entry only on matched fills, without look-ahead. Existing rejected exit overlays remain rejected until independent forward evidence.

## Status
This iteration performs a new arithmetic reconciliation using the actual stored frozen reports. **Historical per-trade market-event replay not performed**; no new observed liquidation count or verified returns claimed.
