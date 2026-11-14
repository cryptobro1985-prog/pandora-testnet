# HYPE STOP vs OPPOSITE_LOCAL manifest gate patch — 2026-11-14 07:30 UTC

Research-only. Existing branch, no detector training, no production change, no orders.

## Concrete code change
Updated `research/hype_terminal_local_strategy/trade_manifest_gate_research.py` to split STOP and OPPOSITE_LOCAL paths. The prior gate required stop fills for every row and therefore structurally rejected valid opposite-local exits. The new gate requires a real stop trigger and stop fill only for STOP; for OPPOSITE_LOCAL it requires the opposite local timestamp, its later *signal availability*, exit order submission, and later exit fill. It forbids stop execution fields on the latter path. Both paths require an identified protective-stop order source, explicit private fill sources, and event/market coverage declarations. Unknown exit reasons and ambiguous temporal ordering fail closed. Stop gaps are calculated only for STOP. Nonfinite prices and inconsistent stop/exit fills are rejected.

## Reproducibility
Run `python research/hype_terminal_local_strategy/trade_manifest_gate_research.py` for 13 embedded synthetic assertions, then run with a JSON list manifest as first argument. These assertions have **not** been executed in this automation environment: direct download into the Python runtime failed due DNS/network isolation. The GitHub connector confirmed the update commit, not test success.

## Frozen research remains unchanged
D250 thresholds: rev_atr > 2.084004943, trade_ratio5 > 0.2727842248, side-normalized flow15 < 0.45047316. Frozen 1% adverse-price cut remains a baseline; no previously rejected MFE overlay is promoted. Historical report has 67 sequential simulated trades, 22 fixed-cut exits, 49.25% positive after modeled costs. The 45 non-stop cases are **not** independently matched to event tapes.

## Critical evidence gaps
No matched 67-row private fill manifest, no execution-level Bybit tick replay, no mark-to-market or liquidation verification, no new OOS or monthly equity results. A declared protective-stop source does not prove that an exchange stop was continuously active or executable. The current gate is a schema/causality prefilter, not execution or liquidation proof. Exact timestamp ties are conservatively rejected because strict ordering is required; exchange sequence IDs would need separate validated handling.

## Next run
Locate frozen per-trade row files and Bybit rich historical tapes; reconcile stable trade IDs and signal-available timestamps, identify missing coverage, then compare unchanged baseline with risk-sized 0.25%-0.5% equity per stop on identical causal execution samples. Do not fabricate private fills from Public Trades or assume no liquidations.
