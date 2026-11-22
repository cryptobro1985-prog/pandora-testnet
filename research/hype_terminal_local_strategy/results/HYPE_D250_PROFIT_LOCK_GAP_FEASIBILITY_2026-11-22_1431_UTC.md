# HYPE D250 profit-lock feasibility under execution gaps — 2026-11-22 14:31 UTC

Research only. No detector retraining, no live orders, no production edits. Frozen D250 and previously rejected MFE overlays remain unchanged.

## Sources checked
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 67 completed local pairs; median future opposite-local *oracle* potential +2.046% from D250 entry; median MFE giveback 61.2% on causal exit; median holding time 7.43 h.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 1% cut, 0.15% round-trip modeled costs, no tight trail; attempted profit overlays rejected.
- `d250_conservative_stop_risk_sizer_20261121.py`, `d250_liquidation_clearance_research_gate_20261121.py`, `d250_combined_risk_gate_20261122.py`: current research gates; no matched event replay.

## New deterministic two-sided stop execution calculation
Let `u` be favorable *price* displacement of a stop trigger from entry (LONG: stop above entry; SHORT: stop below entry). Let `g` be additional adverse fill gap measured as fraction of entry, and `c` be complete round-trip costs measured on notional. Ignoring funding and position-size changes, realized net return on notional under an adverse stop fill is approximately `u - g - c`. A non-negative net locked result therefore requires `u >= g + c`. This is **not** a market prediction or observed fill distribution.

Assume `c=0.15%`, same for both sides; compare explicit hypothetical gap stresses:

| Adverse stop-fill gap | Minimum favorable stop trigger offset to lock nonnegative net |
|---|---:|
| 0.0% | 0.15% |
| 0.25% | 0.40% |
| 0.5% | 0.65% |
| 1.0% | 1.15% |
| 2.0% | 2.15% |

At a +1.0% favorable stop trigger, net result per notional is +0.85% for zero gap, +0.35% for 0.5% gap, -0.15% for 1% gap, and -1.15% for 2% gap. With 0.5% account risk and the existing 1% cut + 2% stress-gap sizing, nominal exposure is only about 0.15873x equity, so the corresponding **hypothetical** equity outcomes are +0.135%, +0.0556%, -0.0238%, and -0.1825%, respectively, before funding. These are calculations, not observed trades.

The frozen report's median +2.046% potential to the *future exact opposite extreme* is oracle geometry, **not** the median attainable MFE or a causally accessible trailing trigger. Nevertheless a 2.15% required profit-lock trigger exceeds this median oracle potential; thus under a 2% gap stress, a net nonnegative locked stop cannot be assumed reachable for a typical trade. The aggregate median does not establish a count of reachable trades, and no policy is promoted from this comparison.

## Separate side mechanics
- LOW -> LONG: a profit-lock stop trigger would be ABOVE long entry; an adverse gap fills BELOW the trigger. LONG net displacement is `(fill-entry)/entry - c`.
- HIGH -> SHORT: a profit-lock stop trigger would be BELOW short entry; an adverse gap fills ABOVE the trigger. SHORT net displacement is `(entry-fill)/entry - c`.
- Both must use event-time Last/Mark/Index stop trigger, spread, order book and fill records; short and long gap distributions may differ. Do not assume symmetric empirical fills from symmetric algebra.
- Funding is omitted and may alter the net break-even trigger, especially with median hold 7.43 h and funding schedules varying by instrument and date.

## Implementation implication
A stop moved to raw entry is **not a guaranteed economic break-even stop**. A break-even/profit-lock overlay must be evaluated net of fees, funding, stop-trigger basis and realistic adverse gaps, and only when its trigger was causally available. A larger profit trigger might never be reached. Maintain the original 1% loss-cut/no-tight-trail baseline as unchanged comparator; retain all rejected overlays as rejected pending matched, chronologically unseen forward evidence.

## Missing for matched replay
The 71 individual signal timestamps and 67 paired execution histories (plus four censored signals), M1 Public Trades/Last/Mark/Index triplets, book depth, funding events, actual fee tiers and order-fill slippage. Without them there is no defensible new monthly equity, MTM DD, stop count, liquidation count, realized MFE retention, or unseen-forward result. No missing rich features have been zero-filled.

## Status
New reproducible algebraic sensitivity audit; **not** an event replay and **not** evidence that profit-lock improves the original baseline. No real orders.
