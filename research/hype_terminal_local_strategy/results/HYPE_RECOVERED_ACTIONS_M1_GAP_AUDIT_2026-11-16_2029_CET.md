# HYPE recovered Actions artifact: real compact-M1 continuity audit — 2026-11-16 20:29 CET

Research only; no orders, no production edits, no detector retraining or threshold changes.

## Newly recovered source
Successfully downloaded the **actual** GitHub Actions artifact ID `13650399622` from `cryptobro1985-prog/pandora-testnet` (ZIP 72,991,140 bytes uncompressed listing total; ZIP ~70 MB on disk). Previously the source-recovery report only identified this artifact, without recovering bytes. Its top-level archive has 28 entries including four historical `compact_1m.jsonl.gz` files, labels, manifests and candidate snapshots. **This is real preserved market-derived compact M1 data, not private fills, full L50 order-event sequence, or an original 67-trade ledger.**

## Newly computed actual row-level continuity
Read each compressed JSONL, sorted `start_ms`, counted unique minutes, duplicates, and all `delta(start_ms)>60000`. All gaps listed below were **not** marked by the row-level `gap` flag (flag count zero); thus simply filtering `gap=true` would silently miss them.

| Period / archive directory | UTC start through final bar start | M1 rows | Duplicate timestamps | Missing interior minutes | Gap boundaries (UTC) |
|---|---|---:|---:|---:|---|
| 01_JUL12_AUG07_FULL_MICRO | Jul 12 17:00 – Aug 06 23:59 | 36,419 | 0 | 1 | Jul 28 22:23 → 22:25 |
| 02_AUG08_SEP01 | Aug 08 00:00 – Aug 31 23:59 | 34,559 | 0 | 1 | Aug 15 08:13 → 08:15 |
| 03_SEP01_OCT01 | Sep 01 00:00 – Sep 30 23:59 | 43,199 | 0 | 1 | Sep 26 23:13 → 23:15 |
| 04_OCT04_NOV03 | Oct 04 00:00 – Nov 02 23:59 | 43,198 | 0 | 2 | Oct 04 01:43 → 01:45; Oct 04 04:18 → 04:20 |
| **Total** | Four separate preserved periods | **157,375** | **0** | **5** | **5 gaps** |

These are **interior** missing minutes, excluding the intentional gaps between preserved periods. No `gap=true` row flags were found. A two-minute distance between consecutive minute starts means one absent minute. This check establishes compact M1 continuity only; it does not establish continuity of mark, book, funding or individual public trades.

## Reproducible exact audit
```python
import zipfile,gzip,json,datetime
p="github-actions-artifact-13650399622.zip" # download GitHub Actions artifact 13650399622
with zipfile.ZipFile(p) as z:
    for name in z.namelist():
        if not name.endswith("compact_1m.jsonl.gz"): continue
        rows=[json.loads(line) for line in gzip.open(z.open(name),"rt")]
        ts=sorted(r["start_ms"] for r in rows)
        holes=[(a,b) for a,b in zip(ts,ts[1:]) if b-a>60000]
        missing=sum((b-a)//60000-1 for a,b in holes)
        print(name,len(rows),len(rows)-len(set(ts)),missing,
              sum(bool(r.get("gap")) for r in rows),
              [(datetime.datetime.fromtimestamp(a/1000,datetime.timezone.utc).isoformat(),
                datetime.datetime.fromtimestamp(b/1000,datetime.timezone.utc).isoformat()) for a,b in holes])
```

## New execution consequence
For a candidate trade whose pre-entry D250 feature window or entry-to-exit path crosses one of the five missing minutes, require `M1_PATH_INCOMPLETE` unless independently recovered event tape bridges it. Never treat zero row-level gap flags as complete coverage. Compact M1 high/low timestamp fields cannot prove order of actual private stop acknowledgement, book fill, mark-price liquidation and stop slippage. The source contains label availability times but does not establish the original frozen 71-entry signal ledger. No individual 67-trade event replay or new net-equity / MTM / liquidation / MFE numbers can responsibly be claimed yet.

## Next direct experiment
Recover immutable 71 signal timestamps and 67 finalized trade IDs, join to these actual M1 bars, explicitly mask five gaps and inter-period gaps, then recover mark/L50 and order events or mark fills MODELED/UNKNOWN. Compare frozen 1% cut + opposite-local baseline against 0.25%/0.5% risk sizing on identical chronological entries; rejected exit overlays remain rejected until unseen forward evidence.

Frozen D250: rev_atr>2.0840049433824706, trade_ratio5>0.2727842248141979, side-normalized flow15<0.4504731635235635. No new branch, no production change, no real orders.
