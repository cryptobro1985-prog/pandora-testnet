# HYPE post-local execution replay — source retention audit
Date: 2026-11-14 15:30 UTC. Research only; no orders, production edits, detector retraining, or new thresholds.

## Concrete branch inventory (GitHub contents API, exact research branch)
Unlike default-branch code search, branch-scoped directory traversal found:
- `research/hype_full_micro_202607/results/LATEST_MANIFEST.json`
- `research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json`
- `research/hype_full_micro_202607/results/LATEST_REPORT.json`
- `research/hype_full_micro_202607/results/RECENT_48H_FROZEN_REPLAY_LATEST.json`
- `research/hype_full_micro_202607/build_full_micro.py`
- `research/hype_full_micro_202607/build_dense_full_micro.py`
- `research/hype_full_micro_202608_late/build_base_late_august.py`
- `research/hype_full_micro_202609/build_base_september.py`
- `research/hype_historical_master/build_master.py`

## Verified manifest fields (not independently verified underlying bytes)
Jul12 17:00–Aug07 00:00 UTC, HYPEUSDT; historical source claimed CryptoHFTData Bybit hourly Parquet/Zstd; 2,733 downloaded files and 4,211,413,622 bytes reported. Source counts: trades 631, orderbook 631, liquidations 337, OI 378, mark 378, ticker 378. 48 strict labels (24 LOW, 24 HIGH), 1,252 candidates, 6,260 snapshots.

**Critical provenance blocker: `raw_files_retained: false`.** The GitHub manifest reports only compact gzip-9 outputs; it does not supply immutable, per-trade raw Public Trades/L50/mark/OI source bytes or their hashes. Consequently the downloaded-file counts are not proof that the raw event tape can currently be replayed. `missing_files` explicitly lists liquidation hours (including duplicates). Account-ratio rows: 0. The feature-availability file reports 116 total points = 86 causal inputs + 28 target/eval + 2 metadata; missing causal input IDs 111–113. Never interpret 116 as 116 contemporaneously observed causal inputs.

The same results directory has `RUN_STATUS.json` with status FAILED for run 42660911066; this is an artifact status, not proof that all historical analyses failed or that any individual source byte is corrupt.

## Concrete causal replay consequence
No honest 67-trade matched execution replay is possible **from these manifest counts alone**. Before claiming matched fills or MFE, locate retained compact per-minute/tick timestamped price/mark paths for each signal, verify hashes, and explicitly mark absent L50/liquidations/OI as UNKNOWN. Public market prints cannot verify private hypothetical fills or stop-order acknowledgements. A replay with only OHLC must use conservative ambiguous-bar stop-first bounds; it cannot reconstruct true intrabar fill ordering.

## Frozen research invariants
Keep D250 thresholds rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. Preserve all 71 accepted first signals and carry four without finalized opposite-local paths as censored MTM, not dropped. 67 completed next-local paths are not independently verified trade fills. 1% adverse cut remains frozen; rejected tight trailing / MFI-flow exit overlays stay rejected.

## Next executable work, not completed in this checkpoint
1. Inspect compact JSON/gzip reports for timestamped paths, signal identifiers and entry/exit timestamps. Determine which of 71 events can be matched without recomputing detector.
2. If retained price paths exist, implement a read-only event-time join for LOW->LONG and HIGH->SHORT, with stop trigger/fill modeled separately and open-position MTM for four censored signals.
3. Compare identical sample and fees/funding/slippage under original exposure and risk-budget 0.25–0.5% equity/trade, 1% aggregate stop risk. Do not assume fills, gap caps or zero liquidations.
4. If paths are absent, retrieve original historical hourly source archives with provenance, without re-training detector, then replay.
5. Never label May/Sep/Oct 2026 as truly unseen forward after they have already been inspected.

## Outcome
This iteration performed a **new branch-scoped source inventory and provenance audit**, not a new historical trade replay. Net PnL, monthly equity, MTM/closed DD, fills, liquidation count and MFE capture remain unverified. No fabricated results.
