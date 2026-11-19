# HYPE D250 execution fee-basis regression — 2026-11-19 16:34 CET

Research-only; no real orders, detector retraining, or production changes.

## Source inspection
Read frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `quote_event_stop_replay_research.py`, and existing manifest gate checkpoint from the requested branch.

## Concrete new finding
The current `quote_event_stop_replay_research.py` computes `costs = notional * roundtrip_cost_fraction`. This is a flat cost on ENTRY notional. If the fee model is a percentage of executed notional on EACH leg, the correct fee is `quantity * (entry_vwap * entry_fee_rate + exit_vwap * exit_fee_rate)` (plus separately recorded funding). Actual rates and maker/taker status must come from the execution assumptions; 0.075% each leg below is only an illustrative decomposition of the earlier 0.15% round-trip assumption.

## Executed regression (4 synthetic cases, all PASS)
One unit entered at $100, each-leg fee rate 0.075%:
| Side | Exit | Fee on both executed notionals | Existing flat entry-notional cost | Difference |
|---|---:|---:|---:|---:|
| LONG | $120 | $0.165 | $0.150 | +$0.015 |
| LONG | $80 | $0.135 | $0.150 | -$0.015 |
| SHORT | $120 | $0.165 | $0.150 | +$0.015 |
| SHORT | $80 | $0.135 | $0.150 | -$0.015 |

Executable: `python research/hype_terminal_local_strategy/fee_basis_execution_regression_20261119.py`. The four regression cases were executed successfully locally before committing the equivalent script. This is a numerical model correction, not a matched historical replay.

## Consequences and controls
The flat fee assumption can systematically overstate PnL on trades exiting above entry and understate it on trades exiting below entry, independent of LONG/SHORT direction. For risk-based sizing, reserve ENTRY fee + worst-case EXIT fee at stop with conservative gap/slippage; include funding on chronological holding periods. Avoid double counting the same 0.15% as both a flat reserve and two actual fees. Keep unchanged baseline cost model as a separately labeled historical benchmark, and compare corrected alternatives on identical matched executions. Do not change frozen D250 thresholds or re-promote rejected exit overlays.

## Evidence gate
No 67-trade matched UTC manifest and bid/ask/L50/mark/funding fill ledger was established in this iteration. Consequently monthly net equity, MTM and closed DD, realized stop gap, liquidations, and MFE retention remain UNKNOWN; prior $100->$531.16 is a historical model output, not an execution-verified forward result. Next: recover immutable 67 trade IDs and per-leg timestamps, verify archive coverage, then event replay with distinct trigger/exec prices and cost per leg.
