# HYPE INTERNAL HARD120 — exact-checkpoint historical audit

This is the final paper-only hard-confirmation contract for broad INTERNAL locals. It does not replace the early learner and cannot flip the core direction.

The rule is deliberately simple: a candidate must originate as a 6h trailing extreme, survive 120 minutes without a more-extreme same-side 6h candidate, retrace at least 40 bps, and recover at least 45% of the causal 180-minute move into the extreme.

**The 120-minute checkpoint is evaluated once.** A recovery that happens later is not retroactively counted as a HARD120 success.

On 120 fully actionable INTERNAL swings in the 2026-10-04..2026-11-03 archive, the first actionable signal was correct 53 times and false 4 times: **92.98% precision and 44.17% recall**.

By side:
- LOW: 26 true / 3 false = 89.66% precision, 43.33% recall.
- HIGH: 27 true / 1 false = 96.43% precision, 45% recall.

Chronological 30-swing blocks:
- 1–30: 100% precision / 50% recall.
- 31–60: 85.71% / 40%.
- 61–90: 92.31% / 40%.
- 91–120: 93.33% / 46.67%.

For true actionable signals, median entry was about 1.293% away from the Local extreme and retained about 44.72% of the full swing.

This audit supersedes the earlier HARD120 counts because the earlier prototype did not enforce exactly the same one-shot checkpoint semantics as live. Continuous recovery crossing after 120 minutes is explicitly rejected.

The thresholds were still selected on this same 30-day archive, so this is historical research evidence, not untouched OOS proof. Promotion remains blocked until the independent forward gate reaches at least 20 completed episodes, 10 true-first, 80% precision and 40% recall.
