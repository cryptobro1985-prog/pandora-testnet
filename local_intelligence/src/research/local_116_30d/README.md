# 10-token Local 116 — 30-day causal research

Research-only local-extreme engine for:
ZEC,HYPE,NEAR,SOL,ENA,1000PEPE,DOGE,SUI,AAVE,WLD.

## Non-negotiable data rules
- Official Bybit daily executed-trade archives are streamed one day at a time.
- Every gzip is CRC-verified and SHA-256 recorded before use.
- Rows must be ordered, schema-valid and duplicate trade IDs are rejected.
- Cross-day continuity and maximum inter-trade gaps are recorded.
- No missing source is silently imputed. Candidate windows crossing a detected gap are excluded.
- Historical L50/orderbook, WS liquidation and other sources that were not actually recorded are NEVER fabricated.
- The canonical 116-point contract is retained with an explicit availability mask.
- Target/evaluation points 83..110 are forbidden from causal model inputs.

## Storage policy
Raw daily archives live only in the ephemeral runner cache. After verification + compaction,
the raw archive and its cache manifest are deleted. Persistent artifacts contain only:
- compact 1-minute structural/flow bars (gzip JSONL);
- candidate-local causal snapshots (gzip JSONL);
- strict/internal offline labels (gzip JSON);
- source/data-integrity manifest;
- feature-availability report;
- frozen discovery model + sealed OOS metrics.

This keeps artifacts small and replayable without retaining millions of redundant trades.

## Local definition and learning
Offline labels use completed H1 pivots and are evaluation-only:
- strict structural: L6/K2, alternating collapsed High/Low;
- internal: L3/K1, also alternating.

Every new rolling structural extreme creates a candidate. For each candidate the system
records causal snapshots at 0/30/60/180/300 seconds while the candidate survives.
The feature plane includes multi-window flow, price response/efficiency, CVD/persistence,
rolling structure, survival/retracement and data-quality masks.

Discovery is chronological; final OOS starts 2026-10-27 and is never used to fit
feature direction, weights or threshold. A pooled 10-token aggregation identifies
features whose sign/effect is stable across tokens and reports OOS precision, recall,
false-local rate and detection delay.

No real orders exist in this package.
