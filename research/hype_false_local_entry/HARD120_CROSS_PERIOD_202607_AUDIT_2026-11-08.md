# HYPE HARD120 — independent July/August cross-period audit

Frozen contract: `INTERNAL_HARD120_CHECKPOINT_V2`. No threshold was changed before this replay.

Source: successful historical full-micro run `42393911761`, data artifact `13585701406`, covering 2026-07-12 17:00 UTC through 2026-08-07 00:00 UTC. The legacy artifact contained STRICT labels only, so current INTERNAL L3/K1 terminal labels were regenerated from its compact M1 using the current teacher contract. This produced 103 finalized INTERNAL labels and 101 actionable episodes.

Result: **37 true-first / 7 false-first = 84.09% precision, 36.63% recall.**

By side:
- LOW: 22/2 = 91.67% precision, 43.14% recall.
- HIGH: 15/5 = 75% precision, 30% recall.

The precision gate passes, but the pre-registered 40% recall gate does not. Therefore HARD120 is **not promoted** from this cross-period test.

The weakness is concentrated in HIGH. The primary HARD120 contract remains frozen; any HIGH-specific rule derived after seeing this period is treated as a cross-period-tuned shadow challenger and must earn its status on future forward data.
