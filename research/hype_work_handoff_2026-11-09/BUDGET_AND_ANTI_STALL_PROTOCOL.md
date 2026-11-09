# HYPE Work budget and anti-stall protocol

This file mirrors the mandatory budget-control section embedded in PROMPT_FOR_WORK_GPT61.md.

Purpose: avoid burning the full Work/Codex allowance on brute force, prevent retry loops, and make every session resumable.

Core operating rules:
- Reuse -> cheap tests -> medium models -> expensive finalists.
- Maximum 3 active hypothesis families per side.
- Kill dominated hypotheses early.
- Never tune against sealed/OOS repeatedly.
- Reserve roughly 25-35% of session capacity for validation, tests, checkpointing and reproducibility.
- Never retry the same stalled expensive operation more than once without changing the plan.
- Maintain WORK_PROGRESS.json and append EXPERIMENT_LEDGER.jsonl after meaningful runs.
- Do not rerun experiments already in the ledger unless the data/code contract changed or the prior result was invalid.
- A session may stop after one useful milestone; it does not need to exhaust available allowance.

See PROMPT_FOR_WORK_GPT61.md for the full mandatory protocol.
