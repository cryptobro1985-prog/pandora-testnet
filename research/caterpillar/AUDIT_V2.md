# Caterpillar Research v2 — audit and implementation record

Base branch audited: `research/caterpillar-causal-engine`, base commit `45a7592609acbbf7233622568131cb63e708fb59`.

Implementation branch: `research/caterpillar-full-research-v2`.

Production PANDORA is not modified by this branch. The research engine is PAPER-only.

## Confirmed research-design gaps in the base implementation

1. **One H1 local rule was both the hypothesis and the execution anchor.** It could test that rule, but it could not answer which causal Local High/Low definition was better.
2. **The executable entry path selected one side from the newest local.** It did not independently record both LONG and SHORT continuation/from-local opportunities on every flow block.
3. **Re-entry evidence was narrow.** A correction flag plus restored control could not distinguish correction depth/duration, opposite efficiency, local integrity and structure.
4. **No operational hourly research surface existed.** Final JSON/profile/report generation was stronger than in-run progress visibility.
5. **No durable crash-resume contract existed for the research run.** Append-only files were protected from mixing but a killed process could not restore all causal state.
6. **Per-token synthesis was descriptive rather than a dedicated LOCAL → STRUCTURE → FLOW → ENTRY → HOLD → MFE → EXIT → RE-ENTRY summary.
7. **Large-participant observations were limited to executed trades.** Public L1 spread/top-size and liquidation context were absent.
8. **Feature outcomes did not preserve per-hypothesis MFE/MAE/capture distributions.**

## v2 changes

### Competing H1 local hypotheses

`research_layer.MultiLocalResearch` evaluates predeclared H1 variants in parallel. New extremes remain FORMING/UPDATED and cannot be confirmed on the extreme hour itself. Confirmation requires later closed-H1 retreat evidence.

At confirmation, causal flow evidence is attached as research labels rather than promoted to an entry gate. Local outcomes record 1h/2h/4h forward close return, MFE, MAE and capture. Flow evidence includes absorption, dominant-flow deceleration, failed dominant price impact, strong opposite response, large-trade context and volume-burst context.

This is intentionally a bounded hypothesis family instead of an unlimited post-hoc parameter grid.

### Independent LONG / SHORT research

Each completed flow block records independent LONG and SHORT hypotheses:

- FROM_LOCAL
- CONTINUATION
- DIRECTIONAL

Accepted and rejected hypotheses retain reasons and a causal snapshot. The existing PAPER execution model remains a control; research observations do not silently mutate its rules in the same evaluation run.

### Price-response and large-participant evidence

New streams retain executed-flow price response/efficiency and observable large-participant-like events. Actor identity remains UNKNOWN.

Optional realtime `--market-context` subscribes to public:

- L1 best bid/ask orderbook context;
- public all-liquidation context.

These are research observations, not mandatory strategy filters.

### HOLD / MFE / exit

MFE/MAE remain tick-by-tick. Each flow-block position mark records all exit predicates in `exit_hypotheses.jsonl`.

When a model holds, the forward outcome of that HOLD / PULLBACK / MICRO_COUNTER_FLOW decision is tagged and evaluated, allowing the research layer to measure whether holding through that state was favorable.

Generic feature outcomes now track not only terminal net bps but also MFE, MAE and MFE-capture distributions.

### Re-entry

The new re-entry research stream retains:

- correction depth;
- correction duration;
- original local integrity;
- structure compatibility;
- original/opposite control;
- original/opposite acceleration;
- own-side absorption;
- relationship to the prior exit MFE/MAE.

These are research hypotheses. The existing PAPER re-entry remains the control model.

### Hourly visibility

The engine writes:

- `research_status.json` periodically;
- `hourly_snapshots.jsonl` each research hour;
- `HOURLY_REPORT_LATEST.md` via the `hourly_report` CLI.

The report is per-token and includes hour-over-hour count deltas.

### Crash/resume

`checkpoint.json` stores causal engine state, profiles, books/positions, MFE/MAE, pending labels, locals, H1 state, research-local state and append-only stream byte offsets.

On resume, streams are truncated to the authoritative checkpoint before state restoration. Historical symbol/day progress is committed with the checkpoint as the atomic commit point.

Resume refuses a changed config, symbol universe, schema or Python-package source hash.

A realtime process gap is explicitly censored. The system does not pretend missing exchange observations did not exist.

### Strategy synthesis

`strategy_synthesis.json` keeps separate per-token candidate families for:

- Local definitions;
- entry;
- HOLD;
- exit;
- re-entry;
- no-trade evidence.

It does not emit a deployment-ready claim. Multi-day evidence remains mandatory.

## Remaining limits

- A 30–60 day real archive run has not been completed by the implementation task itself.
- A six-hour real Bybit OOS run has not been completed by the implementation task itself.
- Funding, queue position and full market impact are not modeled.
- L1 top-of-book is research context, not full-depth liquidity reconstruction.
- A specific market-maker identity cannot be established from these public feeds.
- File checkpoints survive only when `--output` and cache live on persistent storage. An ephemeral container filesystem is not durable persistence.
- Statistical feature selection still requires chronological validation and care with overlapping/serially correlated observations.

See `RUNBOOK_V2.md` for exact commands and operational requirements.
