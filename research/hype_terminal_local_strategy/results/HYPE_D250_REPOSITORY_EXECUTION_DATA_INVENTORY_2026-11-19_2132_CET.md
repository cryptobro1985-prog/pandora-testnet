# D250 execution-replay data inventory — 2026-11-19 21:32 CET

Research only; no training, production change, or real orders.

## Executed inspection
Queried the GitHub recursive tree for branch `research/hype-h1-local-v5-oi-microstructure-20261104` (response `truncated=false`): 1,035 entries, 963 blobs. Inventory by extension: 417 .py, 246 .md, 109 .json, 20 .csv, 2 .jsonl, 2 .gz, 1 .zip; no .parquet/.arrow/.feather/.sqlite/.db/.npz files. The two .gz files are `research/hype_work_handoff_2026-11-09/FALSE_LOCAL_SIGNATURES_HIGH.json.gz` and `FALSE_LOCAL_SIGNATURES_LOW.json.gz`, not identified as event-level quote/mark tapes.

All 20 CSVs are under `research/hype_movement_signature/` except `archive/PANDORA_S1_SAMPLE_2026-11-02.csv` (93 bytes). The movement CSVs are results/rows of different strategy experiments, not evidence of matching D250 67 sequential entry-to-exit executions. The largest JSON is `research/hype_false_local_entry/results/HYPE_ALL_LOCAL_RELATIONSHIP_ATLAS.json` (6,089,715 bytes); its filename does not establish that it contains bid/ask/mark/L50 event tapes. The repository has no CSV/JSONL/parquet data files within `research/hype_terminal_local_strategy/`. The tree inventory alone cannot rule out event data stored remotely, in GitHub Actions artifacts, or in JSON files with unconventional names.

## Cross-checked frozen source reports
`H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 71/71 accepted first signals, 67 completed next-opposite trajectories; 61.2% median MFE giveback under causal K2 opposite-local exits. The report does not provide a 67-row UTC event execution tape.
`HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential simulated trades, 22 fixed-cut exits, 1% adverse cut, fixed 0.15% round-trip notional cost. It contains aggregated end-equity and closed DD but no per-trade quote/mark/fill ledger.

Inspected `quote_event_stop_replay_research.py`: event schema `ts_ms,bid,ask,mark,opposite_available`; the function consumes supplied quote events, not actual stored D250 trade records, and explicitly returns `liquidity_verified=False, liquidation_verified=False`. It does not reconstruct events from the two frozen reports.

## Evidence gate
Matched real execution replay for 67/67: **0 verified from this inspection**; this means not verified, not that no historical data exists elsewhere. New monthly net equity, mark-to-market DD, stop fills, liquidation count, funding, MFE capture, and independent forward metrics: **NOT COMPUTED**. Do not report synthetic tests as historical replay. Preserve 3x/5x baseline as historical *modeled* results only; do not claim that risk 0.25–0.5% produces the same equity curve.

## Required concrete next step
Locate a machine-readable 67-row trade manifest with `trade_id, side, terminal_local_ts_utc, d250_confirmation_ts_utc, entry_ts_utc, entry_price, opposite_confirmation_ts_utc, exit_ts_utc, source_artifact_sha`. Join each interval to actual timestamped bid/ask, mark, L50, Public Trades, funding and liquidation-rule metadata; record per-feed coverage and unknown segments. Only then run paired unchanged baseline and risk-sized alternatives on identical sequential trades, with mark-to-market accounting and non-overlap of reserved capital. If source event streams are not present in Git, inspect existing Actions artifact manifests or the documented external storage paths before requesting recollection; never silently impute missing fields.

## Frozen policy
Do not retrain D250 or adjust thresholds. Do not resurrect rejected MFE/profit overlays without independent evidence. No live trading.
