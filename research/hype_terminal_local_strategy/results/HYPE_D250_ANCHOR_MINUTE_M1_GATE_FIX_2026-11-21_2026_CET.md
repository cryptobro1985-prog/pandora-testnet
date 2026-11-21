# HYPE D250: anchor-minute M1 chronology remediation — 2026-11-21 20:26 CET

## Scope
Research-only modification to existing frozen-D250 pre-entry gate. No detector training, threshold changes, trading orders, production deployment or claims of profitable trades.

## Code changes
Updated `d250_raw_m1_preentry_gate_20261121.py`:
- Include the minute containing the source local extreme in the M1 coverage interval.
- Sort eligible M1 bars by UTC before checking continuity; detect duplicate minute starts and gaps.
- For a same-side extension inside the anchor minute, return `INDETERMINATE_ANCHOR_TICK_ORDER`, because OHLC cannot establish whether the print preceded or followed the actual local-extreme tick.
- For an extension in a later minute, retain the directional rejection `LOW_EXTENDED_BEFORE_ENTRY` or `HIGH_EXTENDED_BEFORE_ENTRY`.
- Require closed-bar coverage through the minute before entry; reject intraminute entries without tick tape and any candle closing after entry.
- Retain LOW->LONG / HIGH->SHORT side binding and original D250 chronological eligibility.

## Reproducibility
Added `test_d250_anchor_chronology_20261121.py` with nine synthetic unittest cases: complete LONG/SHORT coverage, out-of-order CSV, anchor-minute ambiguity on both sides, later extension, duplicate, gap, intraminute entry. Tests are committed but **CI execution has not been verified**.

Run from research directory:
```sh
python -m unittest test_d250_anchor_chronology_20261121.py
```

## Interpretation
This corrects a source-level fail-open scenario, not the economic safety of any trade. The gate does not assert a real fill, order book liquidity, mark-price liquidation safety, stop execution or realized PnL. A same-minute extension needs exact ordered Public Trades with anchor tick provenance to resolve. A PASS only establishes absence of observed same-side extension in a complete M1 interval and chronological metadata; it is not a profitable-trade prediction.

## Remaining blocker for matched execution replay
Original UTC manifest for the 67 sequential frozen-entry trades and matched Bybit trade/L50/funding/mark-price tapes have not been established in this iteration. Do not invent them or report monthly equity, MTM DD, fills, stop counts, liquidations, MFE retention or independent forward performance. Restore source artifacts and SHA256 provenance first. Then compare the unchanged baseline against 0.25%/0.5% equity stop-risk sizing, <=1% aggregate stop risk, mandatory stop, staged entry and previously rejected overlays on identical eligible trades. Preserve original rejection status until independent forward evidence.

## Status
Source fix committed, regression tests committed, CI unverified, full 67-trade event replay not executed. Frozen D250 unchanged.
