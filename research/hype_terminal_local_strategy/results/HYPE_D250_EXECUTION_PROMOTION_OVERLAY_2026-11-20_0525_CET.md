# HYPE D250 execution promotion overlay — 2026-11-20 05:25 CET

Research-only checkpoint. Frozen D250, original 1% stop baseline and rejected MFE overlays unchanged. No training, production changes, or orders.

## New concrete work
Read actual existing 67-trade frozen-risk report, previous adversarial checkpoint and current execution gate from the named branch. Reproduced five independent assertions locally with Python 3 (synthetic, not historical): pre-entry opposite extreme, untrusted synthetic provenance, Mark Price crossing liquidation boundary, SHORT-side chronology, and non-blocked valid chronology. All five passed in an independent minimal audit. Added `execution_promotion_overlay_20261120.py` to the same GitHub branch, without modifying the original gate. The newly committed module's own test has not been run in a checked-out repository; local assertions are independently reproduced, not CI evidence.

## New fail-closed research gate
- BLOCK if opposite strict-local extreme occurs at or before actual entry fill, even when confirmation comes later.
- BLOCK if quote source is missing or not prefixed `bybit:`; note this is a *format check only*, not authentication or cryptographic provenance.
- BLOCK promotion if Mark Price crosses supplied modeled liquidation boundary; do not claim a verified exchange liquidation.
- BLOCK if quote timestamps fall outside the trade interval.
- Even with no blockers return `QUOTE_PROVENANCE_ONLY`, `fill_verified=False`, `liquidation_verified=False`. Never promote to actual-fill evidence without independently reconciled order/fill IDs, L50, fees, funding and event timestamps.

## Historical evidence
No new matched 67-trade event tape recovered. The 67 simulated trades, 3x final $531.16 and closed DD 18.56% remain baseline research results, not realistic stop-fill or MTM-verified performance. Original frozen 1% adverse-price stop and causal opposite-local hold are unchanged. 0.25–0.5% equity stop-risk and 1% aggregate risk remain intended *future replay constraints*, not verified live limits.

## Next step
Recover individual trade IDs and UTC timestamps, then event-order Bybit bid/ask, L50, Mark Price, liquidation, funding and fee history. Replay identical 67 trades and causal entry/exit chronology under unchanged baseline and risk-budget alternatives. No monthly net, MTM DD, fills, stops, liquidations or MFE captured/given-back can responsibly be reported yet.
