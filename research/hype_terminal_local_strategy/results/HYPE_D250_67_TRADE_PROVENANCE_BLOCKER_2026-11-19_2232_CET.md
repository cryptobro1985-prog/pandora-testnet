# HYPE D250 67-trade execution provenance audit — 2026-11-19 22:32 CET

Research-only. Existing branch; frozen D250 unchanged. No training, production edits or real orders.

## New executed source audit
Fetched and inspected, at the requested GitHub ref:
- `results/HYPE_D250_REPOSITORY_EXECUTION_DATA_INVENTORY_2026-11-19_2132_CET.md`
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
- `quote_event_stop_replay_research.py`

## Evidence chain and newly confirmed execution gaps
1. The D250 report says 71 accepted first signals and 67 completed *opposite-local trajectories*. These are not an executable 67-row ledger. The asymmetric report gives only aggregate stop counts, win rate, equity and closed drawdown.
2. The quote replay's Event schema is `ts_ms,bid,ask,mark,opposite_available`. It accepts supplied events but does not load D250 trade timestamps, fetch historical tapes, or join UTC events to trades.
3. Its `stop` trigger is executable bid for LONG and ask for SHORT, not separately specified Bybit stop trigger price. `mark` is returned but is not used to check liquidation-before-stop. `roundtrip_cost_fraction` is charged on entry notional only. It does not ingest funding, L50 depth or per-fill slippage.
4. A quote with `opposite_available=True` is treated as an immediately executable opposite confirmation at that quote timestamp. The source lacks provenance for when the opposite H1 pivot actually became K2-known; passing a retrospective label here would leak future information.
5. The replay tracks best/worst only at observed executable quote events. Missing quotes and gap intervals can hide adverse excursions, liquidation, or a missed stop. The existing inventory found no matched event-level 67-trade tape in Git tree, but this does not exclude remote artifacts.
6. The earlier unified contract explicitly distinguishes LOW from HIGH confirmation persistence and rejects raw opposite flow as exit authority. This is not evidence that any new profit-lock overlay works out-of-sample.

## Decision
**0/67 real per-trade quote/mark/L50 execution paths verified in this audit**. No new historical net PnL, monthly equity, MTM DD, liquidation count, stop-fill count, or MFE captured can be computed honestly. The prior 3x $100->$531.16 and 5x $100->$1308.86 are modeled closed-equity results, not replay-confirmed performance.

## Required next execution step (no threshold fitting)
Recover the immutable 67-row trade manifest with local-extreme UTC, D250-known UTC, first entry quote UTC, K2-known opposite UTC, direction, and original source artifact checksum. Resolve existing Actions/external storage references; then join timestamped Public Trades, bid/ask, mark, L50, liquidation rules and funding. Fail closed on unknown intervals. Run paired unchanged baseline and risk-sized 0.25%-0.5% stop-risk variants with shared costs, mark-to-market DD and non-overlapping capital. Do not report unknown liquidation outcomes as zero.

## Data access boundary
The GitHub connector available in this run exposes artifact retrieval by known workflow run ID, but no general repository-wide workflow-run/artifact listing action. No workflow run ID or 67-row manifest was supplied by the inspected reports. Therefore no Actions ZIP was downloaded in this iteration; artifact absence is not asserted.
