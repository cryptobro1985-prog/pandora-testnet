# HYPE HIGH — preferred forward candidate (2026-11-09)

Research/paper only. Real orders remain OFF.

## Decision

Preferred HIGH forward candidate:

`INTERNAL_HARD120_CHECKPOINT_V2 + HARD120_HIGH_FLOW_SHADOW_V2`

HARD120 primary is unchanged. V2 only recovers selected HIGH candidates below
the primary retrace-fraction threshold and **never authorizes a core flip**.

V2 expansion:
- HIGH only;
- exact HARD120 checkpoint;
- retrace >= 40 bps;
- retrace fraction in [0.35, 0.45);
- first-15m executed seller flow <= -0.08;
- >=100 executed trades;
- additionally: retrace fraction < 0.41 OR absolute retrace >= 75 bps.

## Three-period development result

| Period | True first | False first | Precision | Recall |
|---|---:|---:|---:|---:|
| Jul/Aug 2026 | 20 | 5 | 80.00% | 40.00% |
| Sep 2026 | 30 | 6 | 83.33% | 46.88% |
| Oct/Nov 2026 | 29 | 1 | 96.67% | 48.33% |

All three periods clear the research 80% precision / 40% recall floor.

## Important evidence boundary

This is **not untouched OOS proof**. September was inspected while selecting V2.
Therefore V2 is promoted only to forward scoring. It cannot place real orders and
cannot change core direction. Promotion beyond shadow requires the pre-registered
terminal-forward gate: >=20 completed episodes, >=10 true-first, precision >=80%,
recall >=40%.

## Rejected as preferred HIGH stack

On September, the following full stacks missed the HIGH precision gate:
- HARD120 + HIGH-flow V1: 77.78% precision / 43.75% recall.
- EARLY60 full stack: 77.78% / 43.75%.
- HIGH60 full stack: 78.79% / 40.63%.
- Persistence full stack: 76.47% / 40.63%.

Raw HARD120 remained a strong untouched September baseline at 84.85% precision /
43.75% recall; V2 is selected because its three-period development profile improves
recall while retaining the 80/40 floor.

Workflow evidence: run 42533533417, artifact 13637554654.
