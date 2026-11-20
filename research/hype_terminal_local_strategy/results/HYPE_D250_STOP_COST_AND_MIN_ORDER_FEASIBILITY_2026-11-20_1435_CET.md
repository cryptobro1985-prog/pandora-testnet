# HYPE D250: stop-cost / minimum-order feasibility gate — 2026-11-20 14:35 CET
Research only. Frozen D250 and previously rejected exits unchanged. No live orders.

## Evidence re-read from repository
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: 71/71 accepted first signals, 67 finalized swings; median entry-to-structural-stop 3.14%, median MFE giveback 61.2% on causal opposite-local exits; rich market data not uniform.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 modeled sequential trades, 22 fixed 1% price cuts, 0.15% assumed round-trip fee; 3x and 5x equity exposures, **not** actual execution replay.
- HYPE_D250_GAP_RESERVE_SENSITIVITY_2026-11-20_1332_CET.md: stress-sizing formula N = equity*risk/(stop_fraction + round_trip_fee + adverse_gap_reserve + funding_reserve).

## New deterministic calculation: minimum-order feasibility
Assumptions for *arithmetic only*: equity E=$100, risk r=0.25% or 0.50%, fee f=0.15% of notional round trip, adverse gap reserve g=2%, funding reserve **illustratively zero only** (NOT acceptable as verified replay).
Maximum risk-based notional N=E*r/(s+f+g).
For 1% stop: N=$7.9365 at 0.25% risk; N=$15.8730 at 0.50% risk.
For 3.14% structural stop: N=$4.7259 at 0.25% risk; N=$9.4518 at 0.50% risk.

**Critical gate:** if the instrument's *actual, dated* Bybit minimum notional (or rounded minimum quantity multiplied by executable price) exceeds N, there is NO feasible trade at that risk budget. Do not round UP and silently breach risk. Reject trade or increase equity; do not relax the frozen signal.
Minimum equity required for any minimum executable notional M is E_min = M*(s+f+g+funding_reserve)/r. With illustrative M=$10 (NOT a claim about Bybit HYPE minimum), E_min for 1% stop is $63 at 0.5% risk and $126 at 0.25%; for 3.14% stop, $109.80 at 0.5% and $219.60 at 0.25%. The illustrative M must be replaced by dated instrument metadata and actual entry-side quote.

## Fee burden vs stop
With 1% stop, fee 0.15% consumes 15% of stop-distance loss before gap/funding; with 3.14% structural stop, 4.78%. At 1% stop and 2% gap reserve, fee is 4.76% of total stressed 3.15% price/notional loss. These are arithmetic ratios, not measured execution.
A modeled +0.15% favorable price move only breaks even before funding/slippage if full round-trip fee is 0.15%; any slippage/funding increases the required move. LONG and SHORT need separate executable ask/bid paths.

## Exact causal execution requirements
1. Check local confirmation availability and D250 eligibility **before** quote timestamp. Same-side invalidation/opposite-local confirmation blocks stale entry.
2. For LONG, enter against ask and exit/stop against bid; SHORT enter against bid and cover against ask. Apply actual tick/step quantity rounding, spread, depth and minimum notional. Reject unavailable data rather than substituting mid-price.
3. Risk check AFTER quantity rounding, with fee, funding reserve, gap reserve and aggregate portfolio stop-risk <=1%; check liquidation boundary using dated maintenance-margin tiers and Mark Price.
4. Preserve same 67 timestamps and fees for baseline and variants; mark all missing L50/Mark/funding intervals UNVERIFIED. Do not treat oracle opposite extreme as executable.
5. Report separate LONG/SHORT fill eligibility, rejected-minimum-size trades, gap stops, monthly net equity, MTM DD, liquidation crossings, MFE capture and unseen forward only after matched tape exists.

## Status
New quantitative *minimum-order feasibility* and stop-cost analysis, not new matched historical replay. No verified 67-trade event tape, no verified minimum HYPEUSDT order quantity, no new net-equity or MFE results. D250 frozen, no retraining, no production changes.
