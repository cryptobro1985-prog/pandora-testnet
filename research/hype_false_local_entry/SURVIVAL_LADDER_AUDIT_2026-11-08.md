# HYPE INTERNAL Survival Ladder — HARD90 → HARD120

Frozen paper-only research contract.

The lineage starts only from a 6h trailing extreme and is not reset by the ordinary hourly stale-refresh. A more-extreme same-side 6h candidate resets the lineage.

- **HARD90:** 90 minutes survived, retrace >= 40 bps, and retrace recovers >= 65% of the causal 180-minute pre-move.
- **HARD120 fallback:** 120 minutes survived, retrace >= 40 bps, and retrace recovers >= 45% of the same pre-move.
- One lineage emits only once. Neither rung can flip the core direction.

On 120 fully actionable INTERNAL swings, the combined first-signal result was **54 true / 5 false = 91.53% precision, 45% recall**. The four chronological blocks were:

- episodes 1–30: 100% precision / 53.3% recall;
- 31–60: 87.5% / 46.7%;
- 61–90: 92.3% / 40%;
- 91–120: 85.7% / 40%.

Compared with HARD120 alone, the early rung adds two correct actionable signals without adding a false first signal on this archive.

Important: these thresholds were selected after studying this 30-day history, so the result is not untouched OOS evidence. The contract is now frozen. Promotion depends only on the independent forward actionable first-signal gate.
