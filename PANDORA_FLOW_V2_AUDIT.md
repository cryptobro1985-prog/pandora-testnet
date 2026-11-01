# PANDORA Flow v2: decision-path audit

Experiment: `pandora_flow_v2`. PAPER only. This audit records the source observed
before the Flow v2 changes on 2026-11-01, then documents the replacement and its
verification. The incident-era H1/M15 behavior below is a baseline, not the new
strategy specification.

## Baseline: what influenced trading

| FILE | FUNCTION | CURRENT LOGIC (before Flow v2) | WHY IT IS WRONG for this experiment | WHAT WILL REPLACE IT |
| --- | --- | --- | --- | --- |
| `app.py` | `pandora_win_h1_direction` | Analyzes closed H1; obtains M15 locals, promotes an M15-confirmed forming extreme, preserves the newest candle anchor and writes process-local H1 verification. | Candle structure chooses direction and readiness; fresh executed control cannot independently choose the side. | Pure executed-trade evidence and a persisted flow state machine. Legacy local reconstruction may remain for history only. |
| `app.py` | `pandora_runtime_h1_verified` | Requires a scan by this process, matching signal/pivot candle identifiers and the expected completed H1 hour. | A restart or hour boundary can block OPEN/REENTRY/ADD until candle history catches up. | Fresh tape, sequence validity and independent execution identifiers; timestamps serve freshness only. |
| `app.py` | `pandora_confirmed_h1` | Checks confirmed H1 local, side, signal/pivot times and `h1_direction_anchor`. | H1 is an admission and direction gate. | Flow decision eligibility; no candle anchor requirement. |
| `app.py` | `pandora_open` | Requires both H1 validators, H1 side equality, current anchor equality, fresh forming structure and `entry_structure_valid`; repeats anchor checks after sizing. | OPEN and REENTRY remain dependent on candle direction and candle identifiers even with live flow. | Revalidate the flow decision and mark before committing; feed flow-derived compatibility fields to the unchanged risk planner. |
| `app.py` | `pandora_mark_positions` | Calls `pressure_exit`; a newer opposite H1/M15 execution local can satisfy the price-structure exit alternative. | Candle promotion can change CLOSE timing and therefore reversal readiness. | Flow-confirmed transfer with execution-count hysteresis and material price response. Existing maintenance accounting stays separate. |
| `app.py` | `pandora_flow_fast_entries` | Reads cached H1 analysis, requires runtime H1 proof, chooses its side and clears opposite watch on a new H1 pivot. | Direction, re-entry and reversal are owned by the candle anchor. | A fresh flow FSM decision owns direction and entry kind; post-close executions must independently confirm. |
| `app.py` | `pandora_loop`, `market_history_bootstrap` | Rebuilds H1/M15 analysis each second and wakes the executor; local readiness requires current candle history. | Polling and history availability control when a directional candidate becomes tradable. | Public Trade ingestion updates flow on each accepted new execution; polling only schedules work, persistence or data-loss checks. |
| `pandora_locals.py` | `_closed_m15_local`, `live_locals` | Finds closed-M15 reversal pivots and confirms forming H1 extremes with two closed M15 bars. | M15 close determines when direction can change. | Removed from the active trading dependency graph; retained historical helpers may be inspected independently. |
| `pandora_locals.py` | `execution_anchor` | Promotes a newer M15 reversal, or observed H1 extreme plus M15 confirmation, when sustained flow agrees. | Executed flow corroborates a candle-selected direction instead of selecting direction. | Flow-only control assessment and causal price response. |
| `pandora_locals.py` | `entry_structure_valid` | Rejects SHORT on/above the active HIGH and LONG on/below LOW. | A candle pivot is an additional admission gate. | Existing sizing uses a flow-derived observed price reference; directional admission is the FSM. |
| `local_order_flow.py` | `_candidate`, `initial_entry_candidate`, `entry_candidate` | Uses `analysis.entry_side` and confirmed H1 flags, then checks flow alignment. | OPEN/REENTRY still require H1 direction. | Flow-only FSM entry evidence. |
| `local_order_flow.py` | `_confirmed_counter_control`, `pressure_exit` | Accumulates 3 seconds of countercontrol; resets on >5s event gaps or 15s evidence expiry; opposite confirmed local can replace structural confirmation. | Duration gates delay a sufficient execution sequence, and candles can trigger an exit alternative. | Count independent new executions; counterflow, weakening/absorption, price response, learned noise and costs determine a transfer. |
| `local_order_flow.py` | `update_watch`, `reentry_ready` | Watch uses executed structure but remains constrained by the H1-side candidate in the caller. | Re-entry cannot independently resume a flow-selected side. | Persisted post-close counterflow and independent resumption evidence; no artificial re-entry count cap. |
| `pandora_flow.py` | `summarize`, nested `window_control` | Requires complete 5s/15s windows; `evidence_ready` requires 15s coverage; dominance duration advances at executions and window expirations. | Waiting for coverage and expiry can manufacture readiness without new executions. | Windows are measurement context only. New evidence, control persistence and confirmations advance only on accepted new trade events. |
| `market_data.py` | `RollingMarketData.flow_context` | Summarizes against polling time and uses elapsed coverage; cached summary expires on a clock. | Repeated polling can age old volume into different directional/control evidence. | Recompute directional evidence at the latest exchange event; evaluate receive/exchange freshness separately. |
| `pandora_runtime.py` | `pyramid` | Requires process-local H1 proof before preserved sizing/add planning. | ADD depends on candle history. | Flow-derived adapter plus fresh same-side control; preserve sizing and money constraints. |
| `pandora_runtime.py` | `_cycle_symbol` | Reads `_pandora_analysis`; checks H1 proof before entry; newer opposite local may open after a committed close. | Executor connects the candle side to OPEN/REENTRY/REVERSAL. | Dispatch FSM output from current executed flow; managed legacy positions remain eligible for management. |
| `pandora_win_core.py` | `pyramid_decision` | Requires `analysis.anchor_confirmed` and aligned side. | With the old caller, these fields represent a candle anchor. | Keep sizing/add mechanics; supply those compatibility keys only from confirmed executed-flow evidence. |
| `pandora_risk.py` | `signal_strength`, `adverse_distance`, `plan_entry`, `plan_add` | Sizing consumes anchor/side flags, pivot price, observed range and noise; the module itself reads no candles or market feeds. | Old adapter imports candle evidence into size. Rewriting money management would violate the requested scope. | Preserve this file byte-for-byte. A flow-only adapter supplies aligned control flags, executed price reference and observed noise. Risk geometry remains a planning reference, never a fixed exit. |
| `pandora_scanner.py` / `pandora_runtime.py` | `LiveScanner.rank`, `scanner_snapshot` | Ranking and selected membership can change within the hour; watch cleanup follows rotation. | Entry set is not fixed for an hour. | Persist a top-five snapshot with last/next refresh; only hourly universe refresh changes membership; held symbols become `MANAGED_POSITION`. |

Timestamps used for stale-data detection, contract metadata freshness, lease
fencing, logging and persistence are operational clocks. The single hourly
universe refresh clock selects markets and must never choose the trade side or
force a position close. Fixed-duration rolling measurements are permitted; a
completed measurement window is not an entry or exit event.

## Verification scope

The proof must inspect active entry, management, add and FSM functions, including
their project-local dependencies. Searching the entire repository for `M15`
cannot distinguish a historical test or UI field from an active trading gate.
The executable audit will report the exact inspected functions, matched evidence
and violations. Its negative tests must demonstrate that an injected candle
dependency, a timer bucket and an unreviewed directional helper are rejected.

Acceptance results and reset evidence belong to the final validation artifacts.
No test, production database reset, live Bybit readiness or Render deployment is
claimed by the baseline audit.

Preserved-money-engine baseline SHA-256:

```text
dcc3bee9df53696a08eddbefe36ed73e3d219a956f71d8cf101f0cc0184b6ef3  pandora_risk.py
310bdd2b1988fbe1b2a3d17adf0c7ec73eaa85391599f7a7517664e82553a11e  accounting.py
```

## Implemented Flow v2 boundary

`app.pandora_open` obtains the live `WIN.entry_decision`, checks the actual flow
side, freshness, membership, current mark and the preserved risk plan. It no
longer calls either H1 validator or a candle/local candidate. The incoming
legacy `analysis` argument is replaced by the FSM's flow-derived adapter.

`app.pandora_mark_positions` measures PnL/MFE/MAE and preserves the money engine's
maintenance guard. Discretionary CLOSE comes from
`PandoraRuntime._cycle_symbol` after `FlowStrategy.ingest`; it does not use an
opposite candle local. `pandora_flow_fast_entries` dispatches the same runtime,
rather than a second H1-owned entry path. `pyramid` receives fresh flow adapter
data and retains existing sizing and add constraints.

`FlowStrategy._analysis` produces the old risk API's `anchor_confirmed`,
`entry_side`, `entry_blocked`, `pivot_price` and `pressure_state` from executed
control and traded-price geometry. The unchanged risk engine reads those fields
for size and leverage. Neither adapter nor its dependencies read candle history.

Key changes, shown as abbreviated decision-path comparisons:

```python
# Before: app.pandora_open
if not pandora_confirmed_h1(analysis): reject("H1_NOT_CONFIRMED")
if not pandora_runtime_h1_verified(symbol, analysis): reject("CURRENT_CLOSED_H1_NOT_VERIFIED")
selection = pandora_flow_initial_entry_candidate(symbol, analysis, ..., flow, stamp)

# After: app.pandora_open
decision = WIN.entry_decision(symbol)
# Validate OPEN/REENTRY, actual flow side, freshness and account constraints.
analysis, flow = decision["analysis"], decision["flow"]
plan = plan_entry(..., analysis, flow, ...)

# Before: app.pandora_mark_positions
opposite_local = pandora_runtime_h1_verified(symbol, anchor) and ...
reason = pandora_flow_pressure_exit(..., opposite_local_confirmed=opposite_local)

# After: PandoraRuntime._cycle_symbol
decision = self.strategy.ingest(symbol, event, position=position, ...)
if decision["action"] == "CLOSE":
    a.pandora_close(symbol, mark, "executed_flow_control_transfer", ...)
```

The complete current state machine and hourly persistence/managed-position/data
loss behavior are documented in [README_PANDORA_WIN.md](README_PANDORA_WIN.md).

Hourly universe refresh coordinates a public REST contract-metadata refresh and
current ticker reconciliation. A new hourly selection waits until the contract
catalog was fetched in the current UTC hour; failed/empty observations preserve
the prior persisted selection for retry. This clock and REST readiness choose
market membership only. The continuously running flow executor continues
managing existing positions and does not wait for the refresh to choose a side,
confirm a transfer or close/re-enter/reverse. Hourly metadata scheduling is
therefore outside the directional decision roots audited below.

## Reproducible AST and grep proof

```bash
python scripts/audit_flow_decision_path.py --report validation/flow-decision-path.json
python -m unittest tests.test_flow_v2_decision_path -v
```

The audit starts from `app.pandora_open`, `pandora_mark_positions`,
`pandora_flow_fast_entries`, runtime `pyramid`/`_cycle_symbol`, and core
`pyramid_decision`. It also inspects every function in the pure strategy/core
modules. It follows reviewed project calls, rejects unreviewed dependencies and
dynamic/calendar dispatch, and checks the preserved risk/accounting hashes.
Its JSON includes the complete inspected function list and dependency edges.

The legacy collector summary has exactly one reviewed consumer:
`PandoraRuntime.event_fresh` may read only `trade_data_fresh` from it. The audit
checks that contract. Direction/sizing evidence comes from `FlowStrategy`, not
`pandora_flow.summarize`; calling that old summarizer from the active trading
graph fails the audit. `pandora_flow` contributes measurement horizon/imbalance
constants to the pure strategy. Universe membership, experiment search-path
configuration and lease/database operations are named operational boundaries.

The scoped grep runs over those inspected executable functions. Whole-repository
matches in old history/UI/helpers are not trading dependencies. SQL storage
columns such as `signal_candle_time` remain compatible metadata. The account's
`margin_valuation.complete` means all position marks are known; it is explicitly
distinct from a completed flow measurement window.

Mutation tests reject an injected M15 helper, calendar bucket, duration/window
completion gate, cached candle analysis, unreviewed internal or external
direction helper, directional use of the legacy collector summary, and a change
to the preserved money engine. A historical UI-only M15 helper is correctly
excluded. Static review is complemented by sequence-replay and integration
tests; it is not a general proof of profitability.

Observed focused validation on 2026-11-01: 53 tests passed across
`test_flow_v2_decision_path`, `test_flow_v2_strategy`, `test_flow_v2_universe`,
`test_flow_v2_events` and `test_flow_v2_monitor` using `.venv/bin/python`.
The generated AST report had 82 inspected functions, zero scoped grep matches,
zero violations and unchanged risk/accounting hashes. The report is regenerated
for release; the full-suite result, reset evidence and monitor evidence must be
read from their own validation artifacts rather than inferred from this focused
run.

## Acceptance 1–16: executable test mapping

These are actual tests, not proposed names. Shared parametrized scenarios run
both LONG and SHORT directions. This table identifies coverage; the release
report determines final pass/failure and must include PostgreSQL integrations.

Run `python scripts/run_flow_acceptance.py --report validation/flow-acceptance.json`
with the same isolated database binding as the full release runner. It executes
the unique mapped contracts once, adds active runtime WebSocket/PostgreSQL
OPEN/CLOSE/reversal/restart checks, and emits a separate status for every case.
Missing or skipped tests cannot produce PASS.

Observed final acceptance run at 2026-11-01 19:20 UTC: **16/16 cases PASS**, from 20 unique
explicit tests, no skips, 26.497s. This included the isolated PostgreSQL reset
and actual executor over local WebSocket fixtures. Machine-readable results:
[`validation/flow-acceptance.json`](validation/flow-acceptance.json), with the
execution log in [`validation/flow-acceptance.log`](validation/flow-acceptance.log). The report
explicitly leaves production reset, live exchange and Render deployment
unverified.

| # | Requested behavior | Executable test |
| --- | --- | --- |
| 1 | Clean $500 reset, legacy exclusion, no repeated reset | `tests.test_flow_v2_reset.FlowExperimentResetTests.test_clean_reset_preserves_old_losses_and_new_account_survives_restart` |
| 2 | Continuing 70/30 pump → LONG/HOLD | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_2_continuing_70_30_pump_uses_executed_direction` |
| 3 | LONG micro-pullback → HOLD | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold` |
| 4 | Real exhaustion → CLOSE LONG, independently confirmed SHORT | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_4_6_exhaustion_closes_then_requires_new_executions` |
| 5 | SHORT bounce → HOLD | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold` |
| 6 | Correction exhaustion → CLOSE SHORT, independently confirmed LONG | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_4_6_exhaustion_closes_then_requires_new_executions` |
| 7 | Wall-clock timestamp shifts do not change actions | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_7_receive_wall_clock_changes_do_not_change_decisions` |
| 8 | Repeated polling cannot grow confirmation | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_8_repeated_polling_cannot_increase_any_proof`; `tests.test_flow_v2_events.ExecutionEventTests.test_acceptance_8_polling_never_creates_new_execution_evidence` |
| 9 | Costs/noise prevent churn | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_9_costs_prevent_churn_with_even_strong_counter_volume` |
| 10 | Fixed hourly TOP-5; rotated held positions remain managed | `tests.test_flow_v2_universe.HourlyUniverseTests.test_acceptance_10_entry_set_changes_only_at_hour_and_keeps_positions` |
| 11 | Restart preserves schedule/FSM/account/position/MFE | `tests.test_flow_v2_universe.HourlyUniverseTests.test_acceptance_11_restart_preserves_metadata_and_hourly_cycle`; `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_restart_restores_every_execution_proof_and_close_ack`; `tests.test_flow_v2_reset.FlowExperimentResetTests.test_repeat_command_preserves_live_positions_mfe_and_lease` |
| 12 | Pump resumes after small dip → HOLD LONG | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold` |
| 13 | Correction resumes after small bounce → HOLD SHORT | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold` |
| 14 | Absorbed BUY does not become BUY control | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_14_15_absorbed_volume_never_confirms_control` |
| 15 | Absorbed SELL does not become SELL control | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_14_15_absorbed_volume_never_confirms_control` |
| 16 | Stale tape blocks new direction, exposes uncertainty, separately protects risk and recovers on new executions | `tests.test_flow_v2_strategy.FlowV2StrategyTests.test_acceptance_16_stale_state_blocks_entries_reversal_but_is_not_an_exit` |

No Render deployment is performed by this implementation or the validation
commands. A test-schema reset is not a claim about the production database.
