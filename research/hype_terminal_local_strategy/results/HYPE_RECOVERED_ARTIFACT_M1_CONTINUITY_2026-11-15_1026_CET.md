# HYPE recovered Actions artifact — actual M1 continuity audit (2026-11-15 10:26 CET)

Research only. Existing branch; no detector training, threshold fitting, production change or orders.

## New source recovery
Successfully downloaded GitHub Actions artifact **13650399622** through authenticated GitHub connector. Actual ZIP: 28 entries, 72,991,140 uncompressed bytes (nested source archives included). It contains four `compact_1m.jsonl.gz` datasets, labels, candidate snapshots in two periods, manifests and summary files. This is **not** a private execution tape, tick-level Public Trades or full L50 event stream. Artifact accessibility is now VERIFIED; prior source-recovery blocker is partially resolved.

## Deterministic M1 tape audit
Read each gzipped JSONL, sort by `start_ms`, count adjacent timestamp jumps unequal to 60,000ms; missing minute count = sum(jump/60000 - 1); inspect OHLC ordering, explicit gap flags, duplicates. Check an illustrative ambiguous bar when `high >= open*1.01` AND `low <= open*0.99`; this is NOT a strategy trade.

| Period | Rows | Missing M1 | Gaps | gap=true | Invalid OHLC | Duplicate timestamps | Both +/-1% within bar |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jul12 17:00–Aug06 23:59 UTC | 36,419 | 1 | 1 | 0 | 0 | 0 | 0 |
| Aug08–Aug31 UTC | 34,559 | 1 | 1 | 0 | 0 | 0 | 1 |
| Sep01–Sep30 UTC | 43,199 | 1 | 1 | 0 | 0 | 0 | 0 |
| Oct04–Nov02 UTC | 43,198 | 2 | 2 | 0 | 0 | 0 | 0 |
| **Total** | **157,375** | **5** | **5** | **0** | **0** | **0** | **1** |

Important: five timestamp holes were **not** flagged `gap=true` on surviving rows. A replay must infer gaps from timestamps; never rely solely on the stored gap flag. Entire calendar windows between the four datasets are excluded, not treated as continuous coverage.

## Consequences for causal LONG/SHORT execution
The compact M1 fields include start/end time, OHLC, high/low timestamps, trade counts, buy/sell notionals, flow, and volume. These enable *bar-level* price path bounds, not actual bid/ask fills, stop gap/slippage, queue priority, mark-price liquidation or intrabar trade ordering. A bar containing both sides of a 1% threshold illustrates path-order ambiguity. Even when high_ts/low_ts exist, they do not recover all intermediate stop/exit event ordering.

Next replay must join original frozen D250 signal ledger and original 67 completed + four censored episode IDs with these minute rows using actionable availability times. Keep LOW->LONG ask-entry/bid-stop and HIGH->SHORT bid-entry/ask-stop separate. If event sequence, spread or L50 is missing, report conservative bounds/unknown; never fabricate precise fills. Preserve same fees/funding/slippage and sequential capital accounting. Rich veto fields cannot be zero-imputed.

## Reproduction
Artifact: GitHub Actions 13650399622 in cryptobro1985-prog/pandora-testnet.
For each `*/compact_1m.jsonl.gz` in the ZIP:
```python
import zipfile,gzip,json
z=zipfile.ZipFile("github-actions-artifact-13650399622.zip")
for name in z.namelist():
    if not name.endswith("compact_1m.jsonl.gz"): continue
    rows=sorted((json.loads(x) for x in gzip.decompress(z.read(name)).splitlines() if x),key=lambda r:r["start_ms"])
    missing=sum(max(0,(b["start_ms"]-a["start_ms"])//60000-1) for a,b in zip(rows,rows[1:]))
    ambiguous=sum(r["high"]>=r["open"]*1.01 and r["low"]<=r["open"]*.99 for r in rows)
    print(name,len(rows),missing,ambiguous)
```

## Evidence boundary
No new trade fills, net PnL, MTM/closed DD, liquidation counts, realized MFE or independent forward trading returns established. Frozen D250 and baseline 1% adverse cut unchanged. Previously rejected profit-protection overlays remain rejected.
