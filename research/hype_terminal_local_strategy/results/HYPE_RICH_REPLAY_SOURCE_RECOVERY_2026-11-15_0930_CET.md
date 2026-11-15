# HYPE rich execution replay — verified source recovery audit (2026-11-15 09:30 CET)

Research-only checkpoint. Existing branch; frozen D250 and 1% adverse cut untouched. No orders or production changes.

## New repository inspection (direct GitHub branch reads)
1. `research/hype_full_micro_202607/results/LATEST_MANIFEST.json`: July 12 17:00 UTC–Aug 07 00:00 UTC, 2,733 historical source files (4,211,413,622 downloaded bytes): trades 631, orderbook 631, liquidations 337, OI 378, mark 378, ticker 378. **raw_files_retained=false**; gzip-9 compact outputs. Consequently the manifest does NOT establish the presence of tick-level fill replay inputs in Git.
2. Source has 48 strict labels (24 LOW, 24 HIGH) and 1,252 candidates, **not** a 71-signal execution ledger. 41 unique missing hourly liquidation file paths appear twice in the manifest (82 listed entries). Any replay requiring liquidation veto must mark affected intervals unknown, not zero.
3. `research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json`: 116 points = 86 causal inputs + 28 target/evaluation + 2 metadata. Missing causal input IDs 111,112,113; do not call all 116 usable real-time signals.
4. `research/hype_12p_clean_core/MANIFEST.json`: source GitHub Actions artifact ID **13650399622**, source July 12–Nov 03; only July 17,18,29 are complete UTC rich days, 4,320 compact M1 rows and 496 candidate snapshots. Aug/Sep/Oct rich layers explicitly incomplete. Prior crossed-book validity defect requires masking.
5. The `research/hype_full_micro_202605/202606/202608_late/202609` directories examined contain builders, not raw Parquet. `research/hype_historical_master` and `research/hype_history_backfill` likewise expose builder code. These observations do not rule out external caches or Actions artifacts.

## Consequence for safe trade replay
- Restore artifact 13650399622 (if still available) and list its actual files, timestamps, row schema and retention before attempting a 71-signal join. Do not mistake the 496 snapshot rows for actual fills or the 4,320 M1 bars for tick-ordered stops.
- Recover the frozen 71 signal timestamps, side, availability time and 67 completed + 4 censored episodes from their **original** trade ledger. Match on immutable ID/time, not proximity or retrospective extreme.
- On July 17/18/29, use compact M1 only for coarse OHLC uncertainty bounds; require ordered trades, L50 sequence continuity and private execution/explicit synthetic fill model for definitive stop-fill claims.
- LOW->LONG: first actionable signal timestamp, ask-side entry estimate, bid-side stop sweep; HIGH->SHORT: bid-side entry, ask-side stop sweep. Do not equate public trades with private fills.
- No claim of net return, liquidation count, realized MFE capture or independent forward trading performance is permitted from these manifests.

## Reproducible audit commands
```bash
# On this exact branch:
git show HEAD:research/hype_full_micro_202607/results/LATEST_MANIFEST.json
git show HEAD:research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json
git show HEAD:research/hype_12p_clean_core/MANIFEST.json
# GitHub Actions artifact inventory, if permitted and artifact retained:
gh api repos/cryptobro1985-prog/pandora-testnet/actions/artifacts/13650399622
# Obtain original raw execution tape separately; manifest reports raw_files_retained=false.
```

## Frozen baseline and risk
D250: rev_atr >2.0840049433824706, trade_ratio5 >0.2727842248141979, flow15 <0.4504731635235635. The 71/71 result is historical signal classification, not 71 executed trades. Baseline: 67 completed, 1% adverse cut, no tight trail, 0.15% assumed round-trip cost, opposite K2 available exit. Preserve 0.25–0.5% exploratory stop-risk/trade, total concurrent stress stop-risk <=1% equity; model gaps, liquidation before stop, funding and MTM explicitly. Rejected overlays remain rejected.

## Status
New evidence is a **verified artifact provenance and coverage audit**, not a matched event replay. Full event replay blocked until original source bytes, order sequence and signal ledger are available. No invented performance metrics.
