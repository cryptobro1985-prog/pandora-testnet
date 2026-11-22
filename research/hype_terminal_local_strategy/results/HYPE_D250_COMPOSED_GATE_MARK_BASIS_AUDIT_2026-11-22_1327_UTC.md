# D250 composed liquidation gate: mark-basis sensitivity — 2026-11-22 13:27 UTC

Research only. Frozen D250, 67-trade baseline, rejected MFE overlays unchanged. No detector training, live orders, production edits, or claims of historical fills.

## Source inspected in this branch
- `d250_conservative_stop_risk_sizer_20261121.py`
- `d250_liquidation_clearance_research_gate_20261121.py`
- `d250_combined_risk_gate_20261122.py`
- `results/HYPE_D250_ISOLATED_MARGIN_LIQUIDATION_HEADROOM_2026-11-22_1230_UTC.md`
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`

## New deterministic audit: stop-price and mark-price clearance are not interchangeable
The composed gate calls `gate(state)` before `size(candidate)`. Its current conservative clearance condition is:

`liqdist > adverse_stop_distance + adverse_gap + clearance + abs(mark-entry)/entry + mark_basis_buffer`

For the existing research examples (entry=100, 1% stop, gap=2%, clearance=0.5%, mark-basis buffer=0.1%), the required liquidation distance is **strictly greater than 3.6%** even with mark equal to entry. At a 0.5% entry-to-mark discrepancy the requirement becomes **strictly greater than 4.1%**. These are gate requirements, not actual Bybit liquidation estimates.

| Example liquidation distance | Mark-entry discrepancy | Required distance | Composed clearance |
|---|---:|---:|---|
| 3.5% | 0% | >3.6% | BLOCK |
| 4.0% | 0% | >3.6% | Provisional clearance |
| 4.0% | 0.5% | >4.1% | BLOCK |
| 5.0% | 0.5% | >4.1% | Provisional clearance |

For the diagnostic structural stop at 3.14% with the same gap/clearance/buffer, the minimum requirement is **strictly greater than 5.74%**, rising to **6.24%** with a 0.5% mark-entry discrepancy. At 25x isolated margin, the earlier hypothetical maintenance-reserve screen already showed a potential shortfall; no generic 25x permission should override a verified liquidation-distance gate.

### Risk sizing is a separate gate
For $100 equity, 0.5% account stop-risk, 1% stop, 2% gap and 0.15% assumed total round-trip cost, notional upper bound is $15.8730. With a 3.14% structural stop it is $9.4518. Passing either numerical sizing calculation **does not imply** passing liquidation clearance. Real lot step, minimum notional, maintenance tiers, actual fee schedule, mark trigger basis, and position collateral must be independently verified.

## Newly identified implementation/evidence boundaries
1. `State.authenticated=True` is a caller-supplied Boolean, not cryptographic evidence of a fresh Bybit account snapshot; a production caller could mislabel stale or fabricated liquidation prices. Keep this research-only.
2. `mark_basis=abs(mark-entry)/entry` is intentionally conservative but not a path replay: it cannot establish whether mark-price liquidation would precede a last-price stop or whether stop-market execution would slip past liquidation.
3. `State` has no stop trigger source (Last/Mark/Index), timestamped mark/index/last triplet, risk-tier maintenance, collateral transfer or funding fields. Therefore the gate must not be treated as exchange execution authorization.
4. `d250_combined_risk_gate` correctly blocks mismatch in side/entry/stop/liquidation/gap and existing positions, but still returns `RESEARCH_CANDIDATE_ONLY` on synthetic inputs. It does not reconstruct the 71 UTC signals or the 67 paired trades.

## Required next matched replay
Reconstruct UTC signal id, terminal local id, side, first eligible executable quote, stop trigger source, mark/index/last snapshots, actual liquidation price/tier, stop order/fill, fees/funding, and time-ordered capital reservations. Use the same 67 completed pairs plus four censored accepted signals across baseline, staged entries, fixed/structural stops and any newly challenged profit-lock. Separate LOW->LONG from HIGH->SHORT; do not use exact future opposite extremes. Reject any missing rich microstructure feature rather than imputing zero. Keep rejected profit-protection overlays rejected without unseen forward evidence.

## Evidence status
This run inspected actual repository gate source and performed deterministic algebraic scenario checks. No matched Bybit Public Trades/L50/OI/liquidation event replay, unseen forward result, monthly net equity, MTM drawdown, realized stop fills or liquidation count was produced. The frozen 71/71 historical first-signal result is not a guarantee of executable profitable trades.
