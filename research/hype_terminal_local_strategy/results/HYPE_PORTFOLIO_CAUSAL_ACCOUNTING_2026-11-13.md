# HYPE Safe Local Entries — chronological portfolio accounting checkpoint (2026-11-13)

## Scope and actual work
Continues existing frozen D250 post-local entry and frozen 1% adverse stop research, **not** a new detector training cycle. Read:
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
- `research/hype_all_in_one/MANIFEST.json`
- `research/hype_terminal_local_strategy/results/HYPE_CAUSAL_EXIT_REPLAY_SCAFFOLD_2026-11-13.md`

New reproducible modules:
- `research/hype_terminal_local_strategy/portfolio_accounting_research.py`: chronological single-position compounding with explicit round-trip cost and funding, non-overlap validation, LONG/SHORT grouping, monthly UTC closed-equity reports, max closed DD, and insolvency guard.
- `tests/test_hype_portfolio_accounting_research.py`: six deterministic checks for compounding, overlap rejection, DD, funding, invalid returns and insolvency. Tests are committed, but **not executed in this run**.

This extends the previous single-position exit replay; it is a portfolio accounting scaffold, not a new historical trade replay.

## Critical implementation boundary
The existing `causal_exit_replay_research.py` uses OHLC high/low and gives stop priority, but MFE on a stop bar can use a high/low that happened *after* the stop. Until actual tick order is available, MFE for that bar must be treated as ambiguous, and mark-to-market DD cannot be inferred from closed-only equity. The new portfolio code deliberately does NOT claim intratrade DD or liquidation outcomes.

## Evidence audit
The unified entry contract reports a high-confidence frozen cascade 118 true / 0 false-first on 253 strong episodes (46.64% coverage), and a broader retrospectively meta-selected 256/256 layer that is **not** eligible as proven prospective trade authority. The D250 frozen minimal rule has 71/71 accepted on preserved periods (50/50 in OOS partitions), but median causal exit MFE giveback is 61.2%. These are different cohorts; do not combine them into an invented universal precision estimate.

The `HYPE-HISTORY-20260712-20261103-MASTER`, `local116-HYPE`, `HYPE-RICH-STRONG-*` names in the manifest are artifact *references*, not materialized trade-event rows. Existing July failed run 42660911066 has zero artifacts in the checked run endpoint. No new real-market replay is claimed.

## Required empirical next action
Recover actual entry_ts, exit_ts, entry/exit fill prices, stop fill, available-at confirmation, funding and 1m/tick mark tape for the 67 frozen trades. Feed exactly the same event stream to baseline 3x/5x and risk-sized 0.2x/0.4x/0.8x portfolio replay. Preserve chronology and stop-before-opposite when intrabar order is unknown. For each month and LOW/HIGH side report net compound, trade count, closed and mark-to-market DD, stop breaches/gaps, MFE capture and liquidation distance; keep actual unavailable fields as missing, never zero-impute. Profit-lock variants remain unpromoted until independent forward evidence.

No real orders, production changes, new branch, or claim of safe +30% monthly returns.
