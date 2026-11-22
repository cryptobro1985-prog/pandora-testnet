# HYPE D250 — 71-to-67 survivorship and manifest-schema gate (2026-11-22 18:28 UTC)

Research-only. Frozen entry unchanged; no detector training, production edit, or orders.

## Executed source inspection
Read the frozen D250 walk-forward report, asymmetric risk report, 2026-11-19 branch-specific execution-data inventory, 67-trade provenance blocker, and the actual `d250_trade_replay_manifest_gate.py` at this research branch. Also enumerated the branch's `research/hype_terminal_local_strategy/` (71 entries) and `results/` (236 entries) through the GitHub Contents API, rather than default-branch code search. This confirms the existing replay scaffolding and earlier source inventory are present on the requested branch; it does not establish that remote Actions or external tapes are unavailable.

## New concrete reconciliation finding: the current manifest gate cannot represent the full accepted cohort
The frozen report accepts **71** first signals but has **67** finalized next-opposite trajectories; the 4 others are censored with respect to that endpoint (4/71 = **5.6338%**). The 67-trade asymmetric report is a *completed-trade* result, not a full 71-signal portfolio MTM result.

The existing `d250_trade_replay_manifest_gate.py` requires `exit_utc`, `exit_price`, `exit_reason`, and complete opposite ledger through exit for **every row**. Its `audit()` unconditionally parses `exit_utc`, demands positive `exit_price`, and only accepts STOP or OPPOSITE_CONFIRMED. Thus it structurally **cannot admit an OPEN/CENSORED row** for the 4 signals without fabricating an exit. This is a reproducible schema-level blocker visible directly in source, independent of whether external raw tapes exist.

A second concrete gap: the gate's own declared limitations say it **does not validate same-side invalidation, fills, funding, or overlapping capital**. `d250_signal_utc` is checked against K2 and D250 but no independent `signal_available_utc` / feature ingestion latency or same-side invalidation ledger is verified. Therefore `ELIGIBLE_FOR_EVENT_REPLAY` means only syntactic/declared-coverage eligibility, not executable causality or verified profit.

## Required fix before any 71-signal risk-adjusted claim
Use a separate immutable 71-row cohort ledger (do not rewrite the 67-trade frozen baseline):
- `status = CLOSED_STOP | CLOSED_OPPOSITE | OPEN_AT_CUTOFF | UNKNOWN_DATA`, plus `observation_cutoff_utc`, last observed bid/ask and mark timestamps, quote coverage, and reserved margin.
- Closed rows require independently supported fill time/price; open rows **must not** invent exit price or realize PnL. Instead value open positions using the last **observed** executable quote and contemporaneous mark; if missing, mark MTM/DD as UNKNOWN, not zero.
- Include a 71-row uniqueness check, counts by side and status, `signal_utc >= max(K2_available_utc, D250_utc, feature_available_utc)`, no same-side invalidation before entry, and no opposite K2-known before entry. Ledger event times must have source hashes.
- Treat STOP-vs-OPPOSITE same-minute order as UNKNOWN without tick order; use actual trigger source and gap-aware executable fills, and verify mark-price liquidation separately.
- Report **two distinct** endpoints: the unchanged original 67-completed-trade modeled baseline and the new full 71-signal censored/MTM portfolio. Never treat their equity curves as interchangeable.

## Arithmetic consistency checks (not historical replay)
- Censored proportion = 4/71 = 5.6338%; completed next-opposite proportion = 67/71 = 94.3662%.
- A 67-only terminal equity result omits the unknown valuation of 4 accepted signals. Neither zero PnL nor forced liquidation/closure can be assigned from the source reports.
- For initial equity $100, a risk budget of 0.25%-0.5% is $0.25-$0.50 per position and <=$1 total planned stop risk. This is a sizing constraint, **not** a guarantee against gap losses.

## Evidence / result status
Historical matched quote/mark/L50 paths verified in this inspection: **0/67** (not verified; not proof of nonexistence elsewhere). Monthly net equity, MTM/closed DD on full 71, fills, funding, realized liquidation count, MFE captured/given back and unseen forward: **NOT COMPUTED**. Existing 3x and 5x closed-trade figures remain modeled only.

## Next branch-specific action
Recover the 71 immutable UTC signal records and identify the 4 censored cases; query existing Actions artifact manifests / external data pointers with explicit run IDs and hashes. Once recovered, implement a 71-row status-aware validator alongside the existing 67-row gate, not as a retroactive change to frozen thresholds; then execute paired baseline/0.25%-0.5%-risk replay with identical event tapes, funding, fills, capital reservations, and truly unseen forward data.

No rejected MFE overlays promoted; no orders or production changes.
