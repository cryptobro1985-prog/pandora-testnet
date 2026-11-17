# HYPE historical artifact recovery and M1 continuity audit — 2026-11-17 13:30 CET

Research only. Existing frozen D250 and asymmetric 1% stop unchanged; no retraining, production changes or orders.

## New concrete recovery
Successfully downloaded GitHub Actions artifact **13650399622** via GitHub connector; actual archive 70 MiB, 28 ZIP members. This resolves the prior uncertainty about artifact retention. Archive includes four historical period folders, MASTER_INDEX.json, compact M1 gz streams, labels, and candidate snapshots (NOT private fills or the original 67-trade UTC ledger). Full micro snapshot data in July is *derived candidate snapshots*, not the raw event tape.

## Reproducible compact M1 audit
Read each gzip JSONL member from the recovered ZIP and computed SHA-256 on its compressed bytes; counted rows, explicit gap flags, non-60-second start-time jumps, and availability of within-bar high/low timestamps:

| Period | M1 rows | gap=true | non-60s transitions | both high/low timestamps | compressed SHA256 |
|---|---:|---:|---:|---:|---|
| Jul12-Aug07 | 36,419 | 0 | 1 | 36,419 | 431d140c40cbecb4608b2b2b2565f0297b75ed4a2afbe36ce890e117d57a3385 |
| Aug08-Sep01 | 34,559 | 0 | 1 | 34,559 | ad839052aa0b4f5a35ad0e600e2daf1a54caaab4a7c62a7e23f385341dd74c97 |
| Sep01-Oct01 | 43,199 | 0 | 1 | 43,199 | 968cfd8ee6ba01b3ab12b85bf7974a99cb28399d2c68f5e6fbb3650a3ad24a95 |
| Oct04-Nov03 | 43,198 | 0 | 2 | 43,198 | dea89e1eaf9ad47a0d47564e0880f4cd6e5cdfdc523f750a54777963bbca10ee |

Total **157,375** compact M1 rows. The transitions need UTC inspection before declaring holes (duplicates/out-of-order also count). A zero `gap=true` count does **not** establish continuous market coverage. Within-bar high/low timestamps are helpful for coarse ordering, but are insufficient for realistic bid/ask fills, mark-triggered stops, book depth, or intra-bar liquidity.

## Consequence for original 67-trade replay
Original ledger with immutable trade IDs, signal/entry/exit UTC, stop events, and matching market event tape is still missing from this recovered artifact. Do NOT substitute 6,260 July candidate snapshots for 67 fills or infer that the 67 correspond exactly to the 71 D250 signals. Private historical fills are unavailable for hypothetical trades; execution must be explicitly modeled and stress-tested. The recovered M1 can support a **coarse, explicitly uncertain OHLC replay** only after original ledger recovery. No new net returns, fills, liquidation count, MTM DD or MFE capture are established.

## Reproduce
```python
import zipfile,gzip,json,hashlib
z=zipfile.ZipFile("github-actions-artifact-13650399622.zip")
for p in [n for n in z.namelist() if n.endswith("compact_1m.jsonl.gz")]:
    raw=z.read(p)
    rows=[json.loads(line) for line in gzip.decompress(raw).splitlines()]
    jumps=sum(rows[i]["start_ms"]-rows[i-1]["start_ms"]!=60000 for i in range(1,len(rows)))
    print(p,len(rows),sum(bool(x.get("gap")) for x in rows),jumps,hashlib.sha256(raw).hexdigest())
```

## Next
Resolve exact UTC anomalies; recover 67-row ledger from research scripts/other Actions artifacts; then run identical chronological sample under original 3x/5x baseline and conservative risk-budget alternatives, marking OHLC stop fills uncertain where book/mark data absent. Rejected profit overlays remain rejected.
