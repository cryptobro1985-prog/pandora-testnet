# HYPE Safe Local Entries — execution sequencing stress test, 2026-11-13
Research-only, no real orders. Continues existing frozen post-local entry; no detector retraining.

## Source checks
Read `research/hype_all_in_one/MANIFEST.json`, `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`, and prior `HYPE_POSTLOCAL_SIZING_FRONTIER_2026-11-13.md`. Manifest enumerates master artifact `HYPE-HISTORY-20260712-20261103-MASTER`, `local116-HYPE`, `HYPE-RICH-STRONG-*`, and `HYPE-7LAYER-*`, but listing artifact names is NOT proof of retrieving actual event rows. July failed run 42660911066 has no downloadable run artifacts in its returned first page. This run has NOT materialized matched 67-trade event data.

## New deterministic executable OHLC execution experiment
Locally ran a self-contained Python 3 OHLC sequential replay fixture (6 passing assertions) using frozen 1% underlying stop, 0.15% notional roundtrip fee, 0.10% notional execution slippage, 0.4x equity notional. Explicit rule: if a stop and opposite-local confirmation both occur inside the same OHLC bar, STOP wins; if bar close is beyond stop, fill is worse of stop or bar close, preventing idealized gap fills. Opposite-local exits use the bar close, never the oracle future extreme.

Tests:
1. LONG entry 100, bar H103/L98/C98 and opposite confirmation same bar => STOP at 98, equity -0.90%.
2. SHORT entry 100, bar H102/L97/C102 and opposite confirmation same bar => STOP at 102, equity -0.90%.
3. LONG entry 100, safe bars then opposite confirmation at C102 => exit at 102, equity +0.70%.
4. SHORT entry 100, safe bars then opposite confirmation at C98 => exit at 98, equity +0.70%.
5. LONG entry 100, H101/L99.1/C100.5 with no opposite => remains OPEN.
6. LONG stop-gap to 98 with 0.2x notional => equity -0.45%.

The 0.9% equity stop-gap loss at 0.4x exceeds the planned 0.5% risk budget. Therefore 0.5% is **not a guaranteed worst-case loss** even with 1% stop and nominal slippage reserve. The same bar can first touch a favorable high and then gap through stop: MFE and final PnL cannot be inferred from OHLC ordering.

## Reproducible minimal algorithm
For each chronological OHLC bar, after a causally timestamped entry: update favorable/adverse excursions; evaluate hard stop first; fill at min(stop, close) for LONG or max(stop, close) for SHORT when stop is touched; only if stop absent evaluate causally available opposite confirmation and close at bar close; otherwise hold. Net equity return = account-notional-fraction * (signed exit-price return - 0.0015 - 0.001). This is intentionally pessimistic for gap-stop execution but still not a true orderbook fill simulator.

## Decision
Do not promote the frozen 1% stop as an absolute 0.5% account-loss guarantee. For risk control, size by a stress stop (e.g. 2% underlying adverse move + 0.25% estimated costs => 0.5% risk requires <=0.222x equity notional), and mark stops/gaps separately. This stress number is a scenario, NOT observed HYPE gap distribution.

## Next required real-data run
Retrieve the actual 67 frozen entry/exit rows or reconstruct from HYPE master M1 tape; run unchanged frozen signals with identical bars for 0.2x/0.4x/0.8x and 3x/5x, stop-first ordering, and missing data masks. Use tick/trade tape where available to resolve within-minute order, actual spreads and funding, and compute month-wise equity, intratrade DD, liquidation proximity, MFE/MAE, loss streak, and net returns. Compare LOW and HIGH separately. No new precision, net historical PnL, or liquidation count is claimed here.
