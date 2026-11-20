# HYPE D250 — post-entry stop follow-through, 2026-11-20 19:34 CET

Research only; no orders. Frozen D250 and the 67-trade baseline remain unchanged.

## Verified inputs
Read the existing branch's frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md and entry_quote_failclosed_gate_20261120_1829.py.

## New executable audit
Added `research/hype_terminal_local_strategy/quote_gate_followthrough_audit_20261120.py`. It explicitly separates **entry admissibility at first post-signal quote** from **subsequent stop follow-through**. Later quotes must never retroactively veto an earlier entry; they may trigger a simulated stop. All fills remain unverified and depth, mark/last triggering conventions, latency, funding and liquidation are missing.

Two deterministic synthetic sequences (1-second quote interval, 1% entry-relative stop, hypothetical 0.15% round-trip fee):
- LOW -> LONG: first ask 100.1, initial Mark 100, stop 99.099. Next Mark 98.5 and bid 98.4. Gross exit-price return -1.6983%, hypothetical net -1.8483% of notional.
- HIGH -> SHORT: first bid 99.9, initial Mark 100, stop 100.899. Next Mark 101.5 and ask 101.6. Gross -1.7017%, hypothetical net -1.8517% of notional.

Both first quotes satisfy the earlier quote-only eligibility criteria, yet the next available quotes are beyond the stop. Thus a passed entry gate and a nominal 1% stop **do not bound realized loss to 1%**. This is a synthetic counterexample, not a claim about the actual 67 HYPE trades. Stop execution is not guaranteed at first observed quote and could be worse.

## Methodology safeguard
Do not use the second quote to decide whether the first entry was allowed: that would leak future information. A realistic replay must model stop activation and next executable opposite-side quote with latency and depth; quote-only figures are scenario bounds, not confirmed fills. The original 5-second entry delay, spread and Mark divergence gates are exploratory, not validated OOS filters.

## Blockers
No verified per-trade UTC alignment between frozen D250 signals and actual Bybit L50/Mark/funding event archives was established in this iteration. Therefore historical matched fills=0; monthly net equity, MTM DD, liquidation count, forward net performance and MFE capture are **not established**. Do not replace absent raw data with fabricated events or zero funding.

## Next
Locate and hash source artifacts, extract exact 67 UTC signal timestamps, map each to earliest available post-signal quote and Mark with L50 depth, replay baseline and 0.25%-0.5% equity-risk sizing on identical chronological fills and capital constraints. Rejected MFE overlays remain rejected pending independent evidence.
